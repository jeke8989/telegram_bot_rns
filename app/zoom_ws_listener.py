"""
Zoom WebSocket Event Listener

Connects to Zoom's WebSocket endpoint to receive real-time events
(recording.completed, recording.transcript.completed) instead of HTTP webhooks.
"""

import asyncio
import json
import logging
import uuid
import aiohttp

logger = logging.getLogger(__name__)


class ZoomWSListener:
    """Listens for Zoom events via WebSocket."""

    WS_BASE = "wss://ws.zoom.us/ws"

    def __init__(self, zoom_client, lark_client, db, config,
                 generate_summary_fn=None, generate_structured_fn=None, parse_vtt_fn=None,
                 s3_client=None, auto_transcribe_fn=None):
        self.zoom = zoom_client
        self.lark = lark_client
        self.db = db
        self.config = config
        self.s3 = s3_client
        self.generate_summary = generate_summary_fn
        self.generate_structured = generate_structured_fn
        self.parse_vtt = parse_vtt_fn
        self.auto_transcribe = auto_transcribe_fn
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        """Start the WebSocket listener as a background task."""
        if not self.config.zoom_ws_subscription_id:
            logger.warning("ZOOM_WS_SUBSCRIPTION_ID not set — WebSocket listener disabled")
            return
        if not self.zoom:
            logger.warning("Zoom client not configured — WebSocket listener disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_forever())
        logger.info("Zoom WebSocket listener started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Zoom WebSocket listener stopped")

    async def _get_participants_with_notes(self, meeting_id: int) -> list[dict]:
        """Get meeting participants with their notes."""
        participants = await self.db.get_meeting_participants(meeting_id)
        result = []
        for p in participants:
            note = await self.db.get_staff_note(p['telegram_id'])
            result.append({
                'telegram_id': p['telegram_id'],
                'first_name': p.get('first_name'),
                'username': p.get('username'),
                'note': note,
            })
        return result

    async def _get_host_note(self, host_telegram_id: int | None) -> str:
        """Get the organizer's note from staff_notes."""
        if not host_telegram_id:
            return ""
        return await self.db.get_staff_note(host_telegram_id)

    async def _get_zoom_participants(self, meeting_id: int | str) -> list[dict]:
        """Fetch actual participants from Zoom past meeting API."""
        try:
            if not self.zoom:
                return []
            return await self.zoom.get_past_meeting_participants(meeting_id)
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to get Zoom participants: {e}")
            return []

    async def _get_actual_times(self, meeting_id: int | str) -> tuple[str | None, str | None, int | None]:
        """Fetch actual start_time, end_time, and duration from Zoom past meeting API.

        Returns (start_time_str, end_time_str, actual_duration_minutes).
        """
        try:
            if not self.zoom:
                return None, None, None
            past = await self.zoom.get_past_meeting(meeting_id)
            if not past:
                return None, None, None
            from datetime import datetime
            import zoneinfo
            tz = zoneinfo.ZoneInfo("Europe/Moscow")

            start_str = past.get("start_time")
            end_str = past.get("end_time")
            actual_duration = past.get("duration")

            formatted_start = None
            formatted_end = None

            if start_str:
                dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(tz)
                day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
                month_names = ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
                formatted_start = f"{day_names[dt.weekday()]}, {dt.day} {month_names[dt.month]} в {dt.strftime('%H:%M')} МСК"

            if end_str:
                dt_end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(tz)
                formatted_end = dt_end.strftime('%H:%M') + " МСК"

            return formatted_start, formatted_end, actual_duration
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to get actual times: {e}")
            return None, None, None

    async def _get_meeting_project_name(self, meeting_id: int) -> str | None:
        """Get project name linked to this meeting."""
        try:
            db_meeting = await self.db.get_zoom_meeting(meeting_id)
            if not db_meeting:
                return None
            db_id = db_meeting.get('id')
            if not db_id:
                return None
            projects = await self.db.get_meeting_projects(db_id)
            if projects:
                return projects[0].get('name')
            return None
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: failed to get project name: {e}")
            return None

    def _format_start_time(self, start_time_dt) -> str | None:
        """Format start time for Lark card."""
        if not start_time_dt:
            return None
        import zoneinfo
        from datetime import datetime
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        dt = start_time_dt.astimezone(tz) if hasattr(start_time_dt, 'astimezone') else start_time_dt
        day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        month_names = ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
        return f"{day_names[dt.weekday()]}, {dt.day} {month_names[dt.month]} в {dt.strftime('%H:%M')} МСК"

    def _format_end_time(self, start_time_dt, duration_minutes: int) -> str | None:
        """Calculate and format end time for Lark card."""
        if not start_time_dt or not duration_minutes:
            return None
        import zoneinfo
        from datetime import datetime, timedelta
        tz = zoneinfo.ZoneInfo("Europe/Moscow")
        dt = start_time_dt.astimezone(tz) if hasattr(start_time_dt, 'astimezone') else start_time_dt
        end_dt = dt + timedelta(minutes=duration_minutes)
        return end_dt.strftime('%H:%M') + " МСК"

    async def _generate_short_summary(self, full_summary: str) -> str:
        """Generate a 3-sentence summary from full summary using OpenRouter."""
        api_key = getattr(self.config, 'openrouter_api_key', None)
        model = getattr(self.config, 'openrouter_model', 'gpt-4o')
        if not api_key or not full_summary:
            return ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Ты — ассистент. Сократи саммари встречи до 3 предложений на русском языке. "
                                    "Выдели только самое важное. Отвечай только текстом саммари, без вступлений."
                                ),
                            },
                            {"role": "user", "content": f"Саммари встречи:\n\n{full_summary[:3000]}"},
                        ],
                        "max_tokens": 200,
                    },
                ) as resp:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Short summary generation error: {e}")
            return ""

    async def _listen_forever(self):
        """Reconnect loop with exponential backoff."""
        backoff = 5
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Zoom WS connection error: {e}", exc_info=True)

            if not self._running:
                break

            logger.info(f"Reconnecting Zoom WS in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def _connect_and_listen(self):
        token = await self.zoom.get_access_token()
        sub_id = self.config.zoom_ws_subscription_id
        url = f"{self.WS_BASE}?subscriptionId={sub_id}&access_token={token}"

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, heartbeat=30) as ws:
                logger.info("Connected to Zoom WebSocket")

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(ws, msg.data)
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.error(f"Zoom WS error: {ws.exception()}")
                        break
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                        logger.info("Zoom WS connection closed")
                        break

    async def _handle_message(self, ws, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"Zoom WS non-JSON message: {raw[:200]}")
            return

        module = data.get("module", "")

        if module == "heartbeat":
            await ws.send_str(json.dumps({"module": "heartbeat"}))
            return

        if module == "message":
            content_str = data.get("content", "{}")
            try:
                content_data = json.loads(content_str) if isinstance(content_str, str) else content_str
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse Zoom WS content: {str(content_str)[:300]}")
                return

            event = content_data.get("event", "")
            logger.info(f"Zoom WS event: module={module}, event={event}")

            if event == "recording.completed":
                await self._handle_recording_completed(content_data)
            elif event == "recording.transcript.completed":
                await self._handle_transcript_completed(content_data)
            elif event == "meeting.ended":
                await self._handle_meeting_ended(content_data)
            else:
                logger.info(f"Zoom WS unhandled event: {event}")
            return

        event = data.get("event", "")
        logger.info(f"Zoom WS event: module={module}, event={event}")

    async def _handle_recording_completed(self, data: dict):
        try:
            payload = data.get("payload", {}).get("object", {})
            meeting_id = payload.get("id")
            try:
                meeting_id = int(meeting_id)
            except (TypeError, ValueError):
                logger.error(f"Invalid meeting_id in recording.completed: {meeting_id}")
                return

            topic = payload.get("topic", "Встреча")
            duration = payload.get("duration", 0)
            recording_files = payload.get("recording_files", [])

            share_url = payload.get("share_url", "")
            recording_password = payload.get("recording_play_passcode") or payload.get("password", "")
            
            # Use share_url as primary recording URL (it's embeddable)
            recording_url = share_url
            transcript_download_url = None
            summary_download_url = None

            for rf in recording_files:
                if rf.get("file_type") == "TRANSCRIPT":
                    transcript_download_url = rf.get("download_url")
                elif rf.get("file_type") == "SUMMARY" and rf.get("recording_type") == "summary":
                    summary_download_url = rf.get("download_url")

            # Add password to recording URL if present
            if recording_password and recording_url and "?pwd=" not in recording_url:
                recording_url = f"{recording_url}?pwd={recording_password}"

            transcript_text = ""
            zoom_summary_json = None  # Zoom AI Summary (structured chapters from Zoom)
            
            # Try to download VTT TRANSCRIPT first
            if transcript_download_url:
                logger.info(f"Meeting {meeting_id}: downloading Zoom VTT transcript...")
                try:
                    token = await self.zoom.get_access_token()
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            transcript_download_url,
                            headers={"Authorization": f"Bearer {token}"},
                        ) as resp:
                            if resp.status == 200:
                                transcript_text = await resp.text()
                                logger.info(f"Meeting {meeting_id}: VTT transcript downloaded — {len(transcript_text)} chars")
                            else:
                                logger.error(f"Meeting {meeting_id}: VTT download returned status {resp.status}")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to download VTT transcript: {e}")
            
            # Always try to download Zoom AI SUMMARY (save separately as structured_transcript)
            if summary_download_url:
                logger.info(f"Meeting {meeting_id}: downloading Zoom AI SUMMARY...")
                try:
                    token = await self.zoom.get_access_token()
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            summary_download_url,
                            headers={"Authorization": f"Bearer {token}"},
                        ) as resp:
                            if resp.status == 200:
                                summary_raw = await resp.text()
                                try:
                                    zoom_summary_json = json.loads(summary_raw)
                                    logger.info(f"Meeting {meeting_id}: Zoom AI SUMMARY downloaded — {zoom_summary_json.get('total_items', 0)} items")
                                except Exception:
                                    logger.error(f"Meeting {meeting_id}: failed to parse Zoom SUMMARY JSON")
                            else:
                                logger.error(f"Meeting {meeting_id}: SUMMARY download returned status {resp.status}")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to download SUMMARY: {e}")

            if not transcript_text and not zoom_summary_json:
                logger.warning(
                    f"Meeting {meeting_id}: no TRANSCRIPT or SUMMARY file from Zoom. "
                    "Will poll Zoom API in 10/20/30 min as fallback."
                )

            summary = ""
            # Generate summary from VTT transcript if available, otherwise from Zoom Summary overall_summary
            if transcript_text and self.generate_summary:
                try:
                    summary = await self.generate_summary(transcript_text)
                    logger.info(f"Meeting {meeting_id}: summary generated from VTT — {len(summary)} chars")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: summary generation error: {e}")
            elif zoom_summary_json and zoom_summary_json.get("overall_summary"):
                summary = zoom_summary_json["overall_summary"]
                logger.info(f"Meeting {meeting_id}: using Zoom overall_summary as summary — {len(summary)} chars")

            # Build structured transcript:
            # If VTT available — parse and generate AI structured transcript
            # If only Zoom Summary available — use it directly (already structured)
            structured_transcript_json = None
            if transcript_text and self.parse_vtt and self.generate_structured:
                try:
                    vtt_entries = self.parse_vtt(transcript_text)
                    if vtt_entries:
                        # Convert raw VTT to clean readable text
                        clean_lines = []
                        for e in vtt_entries:
                            h, m, s = e['start_time'].split(':')
                            ts = f"{int(h):d}:{m}" if int(h) > 0 else f"{int(m):d}:{s.split('.')[0]}"
                            prefix = f"[{ts}]"
                            if e.get("speaker"):
                                prefix += f" {e['speaker']}:"
                            clean_lines.append(f"{prefix} {e['text']}")
                        transcript_text = "\n".join(clean_lines)
                        logger.info(f"Meeting {meeting_id}: parsed {len(vtt_entries)} VTT entries, cleaned transcript (WS)")
                        structured_transcript_json = await self.generate_structured(vtt_entries)
                        if structured_transcript_json:
                            logger.info(f"Meeting {meeting_id}: structured transcript generated from VTT (WS)")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: structured transcript error (WS): {e}")
            
            # Fall back to Zoom Summary JSON as structured transcript if no VTT-based one
            if not structured_transcript_json and zoom_summary_json:
                structured_transcript_json = zoom_summary_json
                logger.info(f"Meeting {meeting_id}: using Zoom AI Summary as structured_transcript")

            public_token = uuid.uuid4().hex[:16]

            start_time_raw = payload.get("start_time")  # ISO string from Zoom

            try:
                await self.db.update_meeting_recording(
                    meeting_id=meeting_id,
                    recording_url=recording_url,
                    transcript_text=transcript_text[:50000] if transcript_text else None,
                    summary=summary or None,
                    status="recorded",
                    topic=topic,
                    duration=duration,
                    start_time=start_time_raw,
                )
                await self.db.update_meeting_public_token(meeting_id, public_token)
                if structured_transcript_json:
                    await self.db.update_meeting_structured_transcript(meeting_id, structured_transcript_json)
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to update recording in DB: {e}")

            # Only send Lark card if we have a summary
            if self.lark and summary:
                try:
                    db_meeting = await self.db.get_zoom_meeting(meeting_id)
                    if db_meeting and db_meeting.get("lark_message_id"):
                        try:
                            await self.lark.delete_message(db_meeting["lark_message_id"])
                            logger.info(f"Meeting {meeting_id}: old Lark card deleted")
                        except Exception as e:
                            logger.error(f"Meeting {meeting_id}: failed to delete old Lark card: {e}")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to look up DB for Lark card: {e}")

                webapp_url = getattr(self.config, 'webapp_url', '') or ''
                public_page_url = f"{webapp_url}/meeting/{public_token}" if webapp_url else None

                db_meeting = await self.db.get_zoom_meeting(meeting_id)
                host_name = db_meeting.get('host_name') if db_meeting else None
                host_telegram_id = db_meeting.get('host_telegram_id') if db_meeting else None
                host_note = await self._get_host_note(host_telegram_id)
                participants = await self._get_participants_with_notes(meeting_id)

                actual_start, actual_end, actual_duration = await self._get_actual_times(meeting_id)

                if actual_duration:
                    await self.db.update_meeting_duration(meeting_id, actual_duration)

                start_time_str = actual_start or (self._format_start_time(db_meeting.get('start_time')) if db_meeting else None)
                end_time_str = actual_end or (self._format_end_time(db_meeting.get('start_time'), duration) if db_meeting and db_meeting.get('start_time') else None)

                zoom_participants = await self._get_zoom_participants(meeting_id)
                project_name = await self._get_meeting_project_name(meeting_id)

                short_summary = await self._generate_short_summary(summary)

                try:
                    await self.lark.send_recording_card(
                        topic=topic,
                        recording_url=recording_url,
                        transcript_text=transcript_text[:3000] if transcript_text else None,
                        summary=summary,
                        duration=actual_duration or duration,
                        public_page_url=public_page_url,
                        host_name=host_name,
                        start_time=start_time_str,
                        end_time=end_time_str,
                        participants=participants if participants else None,
                        short_summary=short_summary or None,
                        host_note=host_note or None,
                        zoom_participants=zoom_participants if zoom_participants else None,
                        actual_duration=actual_duration,
                        project_name=project_name,
                    )
                    logger.info(f"Meeting {meeting_id}: recording card sent to Lark (with summary)")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to send Lark recording card: {e}")
            elif self.lark and not summary:
                logger.info(f"Meeting {meeting_id}: Lark card NOT sent — waiting for summary")

            if not transcript_text:
                logger.warning(
                    f"Meeting {meeting_id}: no TRANSCRIPT from Zoom (WS). "
                    "Starting audio-based auto-transcription and polling."
                )
                asyncio.create_task(self._poll_transcript_later(
                    meeting_id, topic, duration, recording_url, public_token,
                ))
                if self.auto_transcribe:
                    asyncio.create_task(self.auto_transcribe(meeting_id))

            asyncio.create_task(self._upload_video_to_s3(meeting_id))
            asyncio.create_task(self._upload_audio_to_s3(meeting_id))

            logger.info(f"Meeting {meeting_id}: recording.completed event fully processed")

        except Exception as e:
            logger.error(f"Error processing recording.completed: {e}", exc_info=True)

    async def _handle_meeting_ended(self, data: dict):
        """Handle meeting.ended event: update Lark card and DB status."""
        try:
            payload = data.get("payload", {}).get("object", {})
            meeting_id = payload.get("id")
            try:
                meeting_id = int(meeting_id)
            except (TypeError, ValueError):
                logger.error(f"Invalid meeting_id in meeting.ended (WS): {meeting_id}")
                return

            topic = payload.get("topic", "Встреча")
            duration = payload.get("duration", 0)
            logger.info(f"Meeting {meeting_id}: meeting.ended (WS) — updating Lark card")

            db_meeting = await self.db.get_zoom_meeting(meeting_id)
            await self.db.update_meeting_status(meeting_id, "ended")

            if self.lark and db_meeting:
                if db_meeting.get("lark_message_id"):
                    try:
                        await self.lark.delete_message(db_meeting["lark_message_id"])
                    except Exception as e:
                        logger.warning(f"Meeting {meeting_id}: failed to delete old Lark card (WS): {e}")

                host_name = db_meeting.get('host_name')
                start_time_str = self._format_start_time(db_meeting.get('start_time'))
                participants = await self._get_participants_with_notes(meeting_id)

                try:
                    result = await self.lark.send_meeting_ended_card(
                        topic=topic,
                        host_name=host_name,
                        start_time=start_time_str,
                        duration=duration or db_meeting.get('duration', 0),
                        participants=participants if participants else None,
                    )
                    new_msg_id = result.get("data", {}).get("message_id")
                    if new_msg_id:
                        await self.db.update_meeting_lark_message_id(meeting_id, new_msg_id)
                    logger.info(f"Meeting {meeting_id}: Lark 'ended' card sent (WS)")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to send Lark ended card (WS): {e}")

        except Exception as e:
            logger.error(f"Error processing meeting.ended (WS): {e}", exc_info=True)

    async def _upload_video_to_s3(self, meeting_id: int):
        """Download MP4 from Zoom and upload to S3 in the background."""
        try:
            if not self.zoom or not self.s3:
                return
            video_result = await self.zoom.download_meeting_video(meeting_id)
            if not video_result:
                logger.info(f"Meeting {meeting_id}: no video available for S3 upload (WS)")
                return
            video_bytes, fmt = video_result
            url = self.s3.upload_video(meeting_id, video_bytes, fmt)
            if url:
                await self.db.update_meeting_video_url(meeting_id, url)
                logger.info(f"Meeting {meeting_id}: video uploaded to S3 via WS -> {url}")
            else:
                logger.error(f"Meeting {meeting_id}: S3 video upload returned None (WS)")
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: _upload_video_to_s3 error (WS): {e}")

    async def _upload_audio_to_s3(self, meeting_id: int):
        """Download audio (M4A/MP4) from Zoom and upload to S3 in the background."""
        try:
            if not self.zoom or not self.s3:
                return
            audio_result = await self.zoom.download_meeting_audio(meeting_id)
            if not audio_result:
                logger.info(f"Meeting {meeting_id}: no audio available for S3 upload (WS)")
                return
            audio_bytes, fmt = audio_result
            url = self.s3.upload_audio(meeting_id, audio_bytes, fmt)
            if url:
                await self.db.update_meeting_audio_url(meeting_id, url)
                logger.info(f"Meeting {meeting_id}: audio uploaded to S3 via WS -> {url}")
            else:
                logger.error(f"Meeting {meeting_id}: S3 audio upload returned None (WS)")
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: _upload_audio_to_s3 error (WS): {e}")

    POLL_DELAYS = [600, 600, 600]  # 10 min, 20 min, 30 min total

    async def _poll_transcript_later(self, meeting_id: int, topic: str, duration: int,
                                     recording_url: str, public_token: str):
        """Background: poll Zoom API for transcript at increasing intervals."""
        for attempt, delay in enumerate(self.POLL_DELAYS, 1):
            await asyncio.sleep(delay)

            db_meeting = await self.db.get_zoom_meeting(meeting_id)
            if db_meeting and db_meeting.get("transcript_text"):
                logger.info(f"Meeting {meeting_id}: transcript already in DB (poll attempt {attempt} — skipping)")
                return

            logger.info(f"Meeting {meeting_id}: polling Zoom API for transcript (attempt {attempt}/{len(self.POLL_DELAYS)})")

            try:
                transcript_text = await self.zoom.download_meeting_transcript(meeting_id)
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: poll attempt {attempt} failed: {e}")
                continue

            if not transcript_text:
                continue

            summary = ""
            if self.generate_summary:
                try:
                    summary = await self.generate_summary(transcript_text)
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: summary generation error during poll: {e}")

            try:
                await self.db.update_meeting_transcript_and_summary(
                    meeting_id=meeting_id,
                    transcript_text=transcript_text[:50000],
                    summary=summary or None,
                )
                logger.info(f"Meeting {meeting_id}: transcript + summary saved via API poll (attempt {attempt})")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to save polled transcript: {e}")
                continue

            # Only send Lark card if we have a summary
            if self.lark and summary:
                if db_meeting and db_meeting.get("lark_message_id"):
                    try:
                        await self.lark.delete_message(db_meeting["lark_message_id"])
                    except Exception:
                        pass

                webapp_url = getattr(self.config, 'webapp_url', '') or ''
                pt = public_token or (db_meeting or {}).get("public_token", "")
                page_url = f"{webapp_url}/meeting/{pt}" if webapp_url and pt else None

                host_name = db_meeting.get('host_name') if db_meeting else None
                host_telegram_id = db_meeting.get('host_telegram_id') if db_meeting else None
                host_note = await self._get_host_note(host_telegram_id)
                participants = await self._get_participants_with_notes(meeting_id)

                actual_start, actual_end, actual_duration = await self._get_actual_times(meeting_id)

                if actual_duration:
                    await self.db.update_meeting_duration(meeting_id, actual_duration)

                start_time_str = actual_start or (self._format_start_time(db_meeting.get('start_time')) if db_meeting else None)
                end_time_str = actual_end or (self._format_end_time(db_meeting.get('start_time'), duration) if db_meeting and db_meeting.get('start_time') else None)

                zoom_participants = await self._get_zoom_participants(meeting_id)
                project_name = await self._get_meeting_project_name(meeting_id)

                short_summary = await self._generate_short_summary(summary)

                try:
                    result = await self.lark.send_recording_card(
                        topic=topic,
                        recording_url=recording_url,
                        transcript_text=transcript_text[:3000],
                        summary=summary,
                        duration=actual_duration or duration,
                        public_page_url=page_url,
                        host_name=host_name,
                        start_time=start_time_str,
                        end_time=end_time_str,
                        participants=participants if participants else None,
                        short_summary=short_summary or None,
                        host_note=host_note or None,
                        zoom_participants=zoom_participants if zoom_participants else None,
                        actual_duration=actual_duration,
                        project_name=project_name,
                    )
                    new_msg_id = result.get("data", {}).get("message_id")
                    if new_msg_id:
                        await self.db.update_meeting_lark_message_id(meeting_id, new_msg_id)
                    logger.info(f"Meeting {meeting_id}: Lark card sent after poll (with summary)")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to update Lark card after poll: {e}")
            elif self.lark and not summary:
                logger.info(f"Meeting {meeting_id}: Lark card NOT sent after poll — no summary yet")

            return

        logger.warning(f"Meeting {meeting_id}: transcript not available after {len(self.POLL_DELAYS)} poll attempts")

    async def _handle_transcript_completed(self, data: dict):
        """Handle recording.transcript.completed — download transcript, generate summary, update Lark."""
        try:
            payload = data.get("payload", {}).get("object", {})
            meeting_id = payload.get("id")
            try:
                meeting_id = int(meeting_id)
            except (TypeError, ValueError):
                logger.error(f"Invalid meeting_id in transcript.completed: {meeting_id}")
                return

            topic = payload.get("topic", "Встреча")
            recording_files = payload.get("recording_files", [])

            logger.info(f"Meeting {meeting_id}: recording.transcript.completed via WS")

            transcript_download_url = None
            for rf in recording_files:
                if rf.get("file_type") == "TRANSCRIPT":
                    transcript_download_url = rf.get("download_url")

            if not transcript_download_url:
                logger.warning(f"Meeting {meeting_id}: no transcript download URL in transcript.completed event")
                return

            transcript_text = ""
            try:
                token = await self.zoom.get_access_token()
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        transcript_download_url,
                        headers={"Authorization": f"Bearer {token}"},
                    ) as resp:
                        if resp.status == 200:
                            transcript_text = await resp.text()
                            logger.info(f"Meeting {meeting_id}: VTT transcript downloaded via transcript.completed — {len(transcript_text)} chars")
                        else:
                            logger.error(f"Meeting {meeting_id}: transcript download returned status {resp.status}")
                            return
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to download transcript: {e}")
                return

            summary = ""
            if transcript_text and self.generate_summary:
                try:
                    summary = await self.generate_summary(transcript_text)
                    logger.info(f"Meeting {meeting_id}: summary generated — {len(summary)} chars")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: summary generation error: {e}")

            try:
                await self.db.update_meeting_transcript_and_summary(
                    meeting_id=meeting_id,
                    transcript_text=transcript_text[:50000],
                    summary=summary or None,
                )
                logger.info(f"Meeting {meeting_id}: transcript/summary updated in DB")
            except Exception as e:
                logger.error(f"Meeting {meeting_id}: failed to update transcript/summary in DB: {e}")

            db_meeting = await self.db.get_zoom_meeting(meeting_id)
            if not db_meeting:
                logger.warning(f"Meeting {meeting_id}: not found in DB for Lark update")
                return

            if self.lark and db_meeting.get("lark_message_id"):
                try:
                    await self.lark.delete_message(db_meeting["lark_message_id"])
                    logger.info(f"Meeting {meeting_id}: old Lark card deleted for transcript update")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to delete old Lark card: {e}")

            # Only send Lark card if we have a summary
            if self.lark and summary:
                recording_url = db_meeting.get("recording_url", "")
                duration = db_meeting.get("duration", 0)
                public_token = db_meeting.get("public_token", "")

                webapp_url = getattr(self.config, 'webapp_url', '') or ''
                public_page_url = f"{webapp_url}/meeting/{public_token}" if webapp_url and public_token else None

                host_name = db_meeting.get('host_name')
                host_telegram_id = db_meeting.get('host_telegram_id')
                host_note = await self._get_host_note(host_telegram_id)
                participants = await self._get_participants_with_notes(meeting_id)

                actual_start, actual_end, actual_duration = await self._get_actual_times(meeting_id)

                if actual_duration:
                    await self.db.update_meeting_duration(meeting_id, actual_duration)

                start_time_str = actual_start or self._format_start_time(db_meeting.get('start_time'))
                end_time_str = actual_end or self._format_end_time(db_meeting.get('start_time'), duration)

                zoom_participants = await self._get_zoom_participants(meeting_id)
                project_name = await self._get_meeting_project_name(meeting_id)

                short_summary = await self._generate_short_summary(summary)

                try:
                    result = await self.lark.send_recording_card(
                        topic=topic,
                        recording_url=recording_url,
                        transcript_text=transcript_text[:3000],
                        summary=summary,
                        duration=actual_duration or duration,
                        public_page_url=public_page_url,
                        host_name=host_name,
                        start_time=start_time_str,
                        end_time=end_time_str,
                        participants=participants if participants else None,
                        short_summary=short_summary or None,
                        host_note=host_note or None,
                        zoom_participants=zoom_participants if zoom_participants else None,
                        actual_duration=actual_duration,
                        project_name=project_name,
                    )
                    new_msg_id = result.get("data", {}).get("message_id")
                    if new_msg_id:
                        await self.db.update_meeting_lark_message_id(meeting_id, new_msg_id)
                    logger.info(f"Meeting {meeting_id}: Lark card updated via transcript.completed (with summary)")
                except Exception as e:
                    logger.error(f"Meeting {meeting_id}: failed to send Lark recording card: {e}")
            elif self.lark and not summary:
                logger.info(f"Meeting {meeting_id}: Lark card NOT sent via transcript.completed — no summary yet")

            logger.info(f"Meeting {meeting_id}: transcript.completed event fully processed")

        except Exception as e:
            logger.error(f"Error processing recording.transcript.completed: {e}", exc_info=True)
