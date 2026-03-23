"""
Zoom Server-to-Server OAuth API Client
"""

import aiohttp
import base64
import time
import logging
import asyncio
from yarl import URL

logger = logging.getLogger(__name__)


class ZoomClient:
    TOKEN_URL = "https://zoom.us/oauth/token"
    API_BASE = "https://api.zoom.us/v2"

    def __init__(self, account_id: str, client_id: str, client_secret: str):
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _basic_auth(self) -> str:
        credentials = f"{self.client_id}:{self.client_secret}"
        return base64.b64encode(credentials.encode()).decode()

    async def get_access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {self._basic_auth()}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "account_credentials",
                    "account_id": self.account_id,
                },
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Zoom token error: {data}")
                    raise Exception(f"Failed to get Zoom token: {data}")

                self._token = data["access_token"]
                self._token_expires_at = time.time() + data.get("expires_in", 3600)
                logger.info("Zoom access token obtained successfully")
                return self._token

    async def create_meeting(
        self,
        topic: str,
        duration_minutes: int,
        start_time: str | None = None,
    ) -> dict:
        """
        Create a Zoom meeting.
        Returns dict with id, join_url, start_url, password, etc.
        """
        token = await self.get_access_token()

        body: dict = {
            "topic": topic,
            "type": 2 if start_time else 1,
            "duration": duration_minutes,
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": True,
                "mute_upon_entry": False,
                "auto_recording": "cloud",
                "waiting_room": False,
            },
        }
        if start_time:
            body["start_time"] = start_time
            body["timezone"] = "Europe/Moscow"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.API_BASE}/users/me/meetings",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            ) as resp:
                data = await resp.json()
                if resp.status not in (200, 201):
                    logger.error(f"Zoom create meeting error: {data}")
                    raise Exception(f"Failed to create Zoom meeting: {data}")

                logger.info(f"Zoom meeting created: id={data['id']}, topic={topic}")
                return data

    async def update_meeting(
        self,
        meeting_id: int | str,
        start_time: str,
        duration_minutes: int,
    ) -> bool:
        """Update scheduled Zoom meeting time/duration."""
        token = await self.get_access_token()
        body: dict = {
            "type": 2,
            "start_time": start_time,
            "duration": duration_minutes,
            "timezone": "Europe/Moscow",
        }

        async with aiohttp.ClientSession() as session:
            async with session.patch(
                f"{self.API_BASE}/meetings/{meeting_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            ) as resp:
                if resp.status == 204:
                    logger.info(
                        f"Zoom meeting updated: id={meeting_id}, start_time={start_time}, duration={duration_minutes}"
                    )
                    return True
                data = await resp.json()
                logger.error(f"Zoom update meeting error: {data}")
                raise Exception(f"Failed to update Zoom meeting: {data}")

    async def get_meeting_details(self, meeting_id: int | str) -> dict | None:
        """Fetch meeting details (status, duration, etc.)."""
        token = await self.get_access_token()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.API_BASE}/meetings/{meeting_id}",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 404:
                    return None
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Zoom meeting details error: {data}")
                    return None
                return data

    async def get_past_meeting(self, meeting_id: int | str) -> dict | None:
        """Fetch past meeting instance details (actual duration, end_time, etc.)."""
        token = await self.get_access_token()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.API_BASE}/past_meetings/{meeting_id}",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 404:
                    return None
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Zoom past meeting error: {data}")
                    return None
                return data

    async def get_meeting_recordings(self, meeting_id: int | str) -> dict | None:
        """Fetch recording details for a meeting."""
        token = await self.get_access_token()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.API_BASE}/meetings/{meeting_id}/recordings",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 404:
                    return None
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Zoom recordings error: {data}")
                    return None
                return data

    async def delete_meeting_recordings(self, meeting_id: int | str) -> bool:
        """Delete all recordings for a meeting."""
        token = await self.get_access_token()

        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{self.API_BASE}/meetings/{meeting_id}/recordings",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 204:
                    logger.info(f"Zoom recordings deleted for meeting {meeting_id}")
                    return True
                elif resp.status == 404:
                    logger.warning(f"No recordings found for meeting {meeting_id}")
                    return False
                else:
                    data = await resp.json()
                    logger.error(f"Failed to delete Zoom recordings for meeting {meeting_id}: {data}")
                    return False

    async def delete_meeting_recordings(self, meeting_id: int | str, action: str = "trash") -> bool:
        """Delete all cloud recordings for a meeting.

        action: 'trash' moves to recycle bin, 'delete' permanently deletes.
        Returns True on success, False if not found or error.
        """
        token = await self.get_access_token()

        async with aiohttp.ClientSession() as session:
            async with session.delete(
                f"{self.API_BASE}/meetings/{meeting_id}/recordings",
                headers={"Authorization": f"Bearer {token}"},
                params={"action": action},
            ) as resp:
                if resp.status == 204:
                    logger.info(f"Zoom recordings deleted for meeting {meeting_id} (action={action})")
                    return True
                if resp.status == 404:
                    logger.warning(f"Zoom recordings not found for meeting {meeting_id}")
                    return False
                data = await resp.json()
                logger.error(f"Zoom delete recordings error {resp.status}: {data}")
                return False

    async def get_past_meeting_instances(self, meeting_id: int | str) -> list[dict]:
        """Fetch all instances (sessions) of a meeting.

        When a meeting is ended and restarted, each session is a separate instance
        with its own UUID and recordings.
        Returns list of dicts with uuid, start_time.
        """
        token = await self.get_access_token()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.API_BASE}/past_meetings/{meeting_id}/instances",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 404:
                    return []
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Zoom past meeting instances error: {data}")
                    return []
                return data.get("meetings", [])

    async def get_meeting_recordings_by_uuid(self, meeting_uuid: str) -> dict | None:
        """Fetch recordings for a specific meeting instance by UUID.

        UUID must be double-encoded if it contains '/' or '//' characters.
        """
        token = await self.get_access_token()
        # Double-encode UUID if it contains / or //
        import urllib.parse
        encoded_uuid = urllib.parse.quote(urllib.parse.quote(meeting_uuid, safe=""), safe="")

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.API_BASE}/meetings/{encoded_uuid}/recordings",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 404:
                    return None
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Zoom recordings by UUID error: {data}")
                    return None
                return data

    async def get_latest_instance_recordings(self, meeting_id: int | str) -> dict | None:
        """Get recordings from the latest (most recent) instance of a meeting.

        If the meeting was stopped and restarted, this returns recordings
        from the last session, not the first one.
        Falls back to regular get_meeting_recordings if no instances found.
        """
        instances = await self.get_past_meeting_instances(meeting_id)
        if not instances:
            logger.info(f"Meeting {meeting_id}: no instances found, falling back to direct recordings")
            return await self.get_meeting_recordings(meeting_id)

        # Sort by start_time descending, pick the latest
        instances.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        latest = instances[0]
        latest_uuid = latest.get("uuid", "")
        logger.info(
            f"Meeting {meeting_id}: {len(instances)} instance(s) found, "
            f"using latest UUID={latest_uuid} (started {latest.get('start_time')})"
        )

        recordings = await self.get_meeting_recordings_by_uuid(latest_uuid)
        if recordings:
            return recordings

        logger.warning(f"Meeting {meeting_id}: latest instance has no recordings, falling back to direct")
        return await self.get_meeting_recordings(meeting_id)

    async def get_past_meeting_participants(self, meeting_id: int | str) -> list[dict]:
        """Fetch participants who actually joined a past meeting.

        Returns list of dicts with name, user_email, join_time, leave_time, duration.
        """
        token = await self.get_access_token()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.API_BASE}/past_meetings/{meeting_id}/participants",
                headers={"Authorization": f"Bearer {token}"},
                params={"page_size": 100},
            ) as resp:
                if resp.status == 404:
                    return []
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Zoom past meeting participants error: {data}")
                    return []
                return data.get("participants", [])

    async def _download_zoom_file(self, meeting_id: int | str, download_url: str, label: str) -> bytes | None:
        """Download a file from Zoom's download URL.

        Zoom redirects to a CloudFront CDN signed URL. aiohttp re-encodes the URL
        and breaks the signature, so we get the redirect manually and use
        yarl.URL(encoded=True) to preserve the exact CDN URL.
        """
        token = await self.get_access_token()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                download_url,
                headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
            ) as resp:
                if resp.status not in (301, 302, 303, 307, 308):
                    if resp.status == 200:
                        ct = resp.headers.get("Content-Type", "")
                        if "html" not in ct.lower():
                            data = await resp.read()
                            if len(data) > 10000:
                                logger.info(f"Meeting {meeting_id}: {label} downloaded directly — {len(data)} bytes")
                                return data
                        logger.warning(f"Meeting {meeting_id}: {label} got HTML on direct download")
                    else:
                        logger.error(f"Meeting {meeting_id}: {label} download status {resp.status}")
                    return None
                cdn_url = resp.headers.get("Location", "")

            if not cdn_url:
                logger.error(f"Meeting {meeting_id}: {label} redirect with no Location")
                return None

            # Use yarl.URL(encoded=True) to prevent aiohttp from re-encoding
            # the CloudFront signed URL (which breaks the signature)
            async with session.get(
                URL(cdn_url, encoded=True),
                allow_redirects=True,
            ) as cdn_resp:
                if cdn_resp.status == 200:
                    ct = cdn_resp.headers.get("Content-Type", "")
                    if "html" not in ct.lower():
                        data = await cdn_resp.read()
                        if len(data) > 10000:
                            logger.info(f"Meeting {meeting_id}: {label} downloaded via CDN — {len(data)} bytes")
                            return data
                    logger.warning(f"Meeting {meeting_id}: {label} CDN returned HTML")
                else:
                    logger.error(f"Meeting {meeting_id}: {label} CDN download failed {cdn_resp.status}")
        return None

    async def download_meeting_audio(self, meeting_id: int | str, instance_uuid: str | None = None) -> tuple[bytes, str] | None:
        """Download audio (M4A) or video (MP4) file for a meeting.

        Returns (file_bytes, format) or None if not available.
        Prefers M4A over MP4 since it's smaller.
        If instance_uuid is provided, fetches from that specific instance.
        Otherwise uses the latest instance if the meeting was restarted.
        """
        if instance_uuid:
            recordings = await self.get_meeting_recordings_by_uuid(instance_uuid)
        else:
            recordings = await self.get_latest_instance_recordings(meeting_id)
        if not recordings:
            logger.info(f"Meeting {meeting_id}: no recordings found for audio download")
            return None

        recording_files = recordings.get("recording_files", [])
        download_url = None
        fmt = "m4a"

        for rf in recording_files:
            if rf.get("file_type") == "M4A":
                download_url = rf.get("download_url")
                fmt = "m4a"
                break

        if not download_url:
            for rf in recording_files:
                if rf.get("file_type") == "MP4":
                    download_url = rf.get("download_url")
                    fmt = "mp4"
                    break

        if not download_url:
            file_types = [rf.get("file_type") for rf in recording_files]
            logger.info(f"Meeting {meeting_id}: no M4A/MP4 file found, available: {file_types}")
            return None

        data = await self._download_zoom_file(meeting_id, download_url, f"audio ({fmt})")
        return (data, fmt) if data else None

    async def download_meeting_video(self, meeting_id: int | str) -> tuple[bytes, str] | None:
        """Download MP4 video file for a meeting.

        Returns (file_bytes, 'mp4') or None if not available.
        Uses the latest instance if the meeting was restarted.
        """
        recordings = await self.get_latest_instance_recordings(meeting_id)
        if not recordings:
            logger.info(f"Meeting {meeting_id}: no recordings found for video download")
            return None

        recording_files = recordings.get("recording_files", [])
        download_url = None

        for rf in recording_files:
            if rf.get("file_type") == "MP4":
                download_url = rf.get("download_url")
                break

        if not download_url:
            file_types = [rf.get("file_type") for rf in recording_files]
            logger.info(f"Meeting {meeting_id}: no MP4 file found, available: {file_types}")
            return None

        data = await self._download_zoom_file(meeting_id, download_url, "video (mp4)")
        return (data, "mp4") if data else None

    async def download_meeting_transcript(self, meeting_id: int | str, instance_uuid: str | None = None) -> str | None:
        """Poll Zoom API for a meeting's transcript and download it.

        Returns the VTT transcript text, or None if not available yet.
        If instance_uuid is provided, fetches from that specific instance.
        Otherwise uses the latest instance if the meeting was restarted.
        """
        if instance_uuid:
            recordings = await self.get_meeting_recordings_by_uuid(instance_uuid)
        else:
            recordings = await self.get_latest_instance_recordings(meeting_id)
        if not recordings:
            logger.info(f"Meeting {meeting_id}: no recordings found via API")
            return None

        recording_files = recordings.get("recording_files", [])
        file_types = [rf.get("file_type") for rf in recording_files]
        logger.info(f"Meeting {meeting_id}: API poll — file types: {file_types}")

        transcript_url = None
        for rf in recording_files:
            if rf.get("file_type") == "TRANSCRIPT":
                transcript_url = rf.get("download_url")
                break

        if not transcript_url:
            logger.info(f"Meeting {meeting_id}: no TRANSCRIPT file in recordings yet")
            return None

        token = await self.get_access_token()
        async with aiohttp.ClientSession() as session:
            # Step 1: follow redirect manually so Authorization header is NOT forwarded to CDN
            async with session.get(
                transcript_url,
                headers={"Authorization": f"Bearer {token}"},
                allow_redirects=False,
            ) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    logger.info(f"Meeting {meeting_id}: transcript downloaded directly — {len(text)} chars")
                    return text
                if resp.status in (301, 302, 303, 307, 308):
                    cdn_url = resp.headers.get("Location", "")
                else:
                    logger.error(f"Meeting {meeting_id}: transcript download returned status {resp.status}")
                    return None

            if not cdn_url:
                logger.error(f"Meeting {meeting_id}: transcript redirect with no Location header")
                return None

            # Step 2: follow CDN URL without Authorization header (pre-signed URL)
            from yarl import URL as YarlURL
            async with session.get(
                YarlURL(cdn_url, encoded=True),
                allow_redirects=True,
            ) as cdn_resp:
                if cdn_resp.status == 200:
                    text = await cdn_resp.text()
                    logger.info(f"Meeting {meeting_id}: transcript downloaded via CDN — {len(text)} chars")
                    return text
                else:
                    logger.error(f"Meeting {meeting_id}: transcript CDN download failed {cdn_resp.status}")
                    return None
