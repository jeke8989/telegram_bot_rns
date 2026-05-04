"""
Lark (Feishu) Bot API Client
"""

import aiohttp
import time
import json
import logging

from app.retry import retry_async

logger = logging.getLogger(__name__)


class LarkClient:
    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

    def __init__(self, app_id: str, app_secret: str, group_chat_id: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.group_chat_id = group_chat_id
        self._token: str | None = None
        self._token_expires_at: float = 0

    @retry_async(attempts=3, base_delay=1.0)
    async def get_tenant_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            ) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    logger.error(f"Lark token error: {data}")
                    raise Exception(f"Failed to get Lark token: {data}")

                self._token = data["tenant_access_token"]
                self._token_expires_at = time.time() + data.get("expire", 7200)
                logger.info("Lark tenant token obtained successfully")
                return self._token

    @retry_async(attempts=3, base_delay=0.5)
    async def _send_message(self, msg_type: str, content: str) -> dict:
        token = await self.get_tenant_token()

        params = {"receive_id_type": "chat_id"}

        body = {
            "receive_id": self.group_chat_id,
            "msg_type": msg_type,
            "content": content,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.MSG_URL,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=body,
            ) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    logger.error(f"Lark send message error: {data}")
                    raise Exception(f"Failed to send Lark message: {data}")
                logger.info(f"Lark message sent: {msg_type}")
                return data

    async def delete_message(self, message_id: str) -> bool:
        """Delete a Lark message by its ID."""
        token = await self.get_tenant_token()
        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"

        async with aiohttp.ClientSession() as session:
            async with session.delete(
                url,
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    logger.error(f"Lark delete message error: {data}")
                    raise Exception(f"Failed to delete Lark message: {data}")
                logger.info(f"Lark message deleted: {message_id}")
                return True

    async def send_meeting_card(
        self,
        topic: str,
        duration: int,
        join_url: str,
        start_url: str,
        host_name: str,
        start_time: str | None = None,
        end_time: str | None = None,
        participants: list[dict] | None = None,
        host_note: str | None = None,
        password: str | None = None,
        project_name: str | None = None,
        card_title: str | None = None,
    ) -> dict:
        """Send an interactive card about a Zoom meeting (created or rescheduled)."""

        duration_label = f"{duration} мин"
        if duration >= 60:
            hours = duration // 60
            mins = duration % 60
            duration_label = f"{hours} ч" + (f" {mins} мин" if mins else "")

        fields = [
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**📌 Тема:**\n{topic}",
                },
            },
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**⏱ Длительность:**\n{duration_label}",
                },
            },
        ]

        if start_time:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**🕐 Начало:**\n{start_time}",
                },
            })

        if end_time:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**🕐 Окончание:**\n{end_time}",
                },
            })

        host_label = host_name
        if host_note and host_note.strip():
            host_label = host_note.strip()
        fields.append({
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**👤 Организатор:**\n{host_label}",
            },
        })

        if project_name:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**📁 Проект:**\n{project_name}",
                },
            })

        elements = [
            {
                "tag": "div",
                "fields": fields,
            },
        ]

        if participants and len(participants) > 0:
            participant_lines = []
            for p in participants:
                note = (p.get('note') or '').strip()
                username = (p.get('username') or '').strip()
                first_name = (p.get('first_name') or '').strip()
                last_name = (p.get('last_name') or '').strip()
                full_name = f"{first_name} {last_name}".strip()

                if note:
                    participant_lines.append(note)
                elif username:
                    participant_lines.append(f"@{username}")
                elif full_name:
                    participant_lines.append(full_name)
                else:
                    participant_lines.append('Участник')

            participants_text = "\n".join(participant_lines)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**👥 Участники ({len(participants)}):**\n{participants_text}",
                },
            })

        if password:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**🔑 Пароль:** {password}",
                },
            })

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "🔗 Присоединиться к встрече",
                    },
                    "type": "primary",
                    "url": join_url,
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "🎬 Начать встречу (хост)",
                    },
                    "type": "default",
                    "url": start_url,
                },
            ],
        })

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": card_title or "📹 Новая Zoom-встреча создана",
                },
                "template": "blue",
            },
            "elements": elements,
        }

        content = json.dumps(card)
        return await self._send_message("interactive", content)

    async def send_recording_card(
        self,
        topic: str,
        recording_url: str,
        transcript_text: str | None,
        summary: str | None,
        duration: int,
        public_page_url: str | None = None,
        host_name: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        participants: list[dict] | None = None,
        short_summary: str | None = None,
        host_note: str | None = None,
        zoom_participants: list[dict] | None = None,
        actual_duration: int | None = None,
        project_name: str | None = None,
    ) -> dict:
        """Send an interactive card about a completed meeting recording."""

        display_duration = actual_duration if actual_duration else duration
        duration_label = f"{display_duration} мин"
        if display_duration and display_duration >= 60:
            hours = display_duration // 60
            mins = display_duration % 60
            duration_label = f"{hours} ч" + (f" {mins} мин" if mins else "")

        fields = [
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**📌 Тема:**\n{topic}",
                },
            },
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**⏱ Длительность:**\n{duration_label}",
                },
            },
        ]

        if start_time:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**🕐 Начало:**\n{start_time}",
                },
            })

        if end_time:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**🕐 Окончание:**\n{end_time}",
                },
            })

        if host_name:
            host_label = host_name
            if host_note and host_note.strip():
                host_label = host_note.strip()
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**👤 Организатор:**\n{host_label}",
                },
            })

        if project_name:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**📁 Проект:**\n{project_name}",
                },
            })

        elements = [
            {
                "tag": "div",
                "fields": fields,
            },
        ]

        all_participant_lines = []

        if participants and len(participants) > 0:
            for p in participants:
                note = p.get('note', '')
                first_name = p.get('first_name') or p.get('username') or 'Участник'
                if note:
                    all_participant_lines.append(f"{note} ({first_name})")
                else:
                    all_participant_lines.append(first_name)

        if zoom_participants and len(zoom_participants) > 0:
            known_names = set(line.lower() for line in all_participant_lines)
            for zp in zoom_participants:
                zp_name = zp.get('name', '').strip()
                if not zp_name:
                    continue
                if zp_name.lower() in known_names:
                    continue
                already_listed = any(zp_name.lower() in kn for kn in known_names)
                if already_listed:
                    continue
                dur_sec = zp.get('duration', 0)
                if dur_sec and dur_sec > 60:
                    dur_min = dur_sec // 60
                    all_participant_lines.append(f"{zp_name} ({dur_min} мин)")
                else:
                    all_participant_lines.append(zp_name)
                known_names.add(zp_name.lower())

        if all_participant_lines:
            participants_text = "\n".join(all_participant_lines)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**👥 Участники ({len(all_participant_lines)}):**\n{participants_text}",
                },
            })

        elements.append({"tag": "hr"})

        if short_summary:
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**📝 Краткое саммари:**\n{short_summary}",
                    },
                }
            )
            elements.append({"tag": "hr"})

        actions = []
        if recording_url:
            actions.append(
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "▶️ Смотреть запись",
                    },
                    "type": "primary",
                    "url": recording_url,
                }
            )
        if public_page_url:
            actions.append(
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "📄 Детали встречи",
                    },
                    "type": "default",
                    "url": public_page_url,
                }
            )

        if actions:
            elements.append({"tag": "action", "actions": actions})

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🎬 Запись встречи готова",
                },
                "template": "green",
            },
            "elements": elements,
        }

        content = json.dumps(card)
        return await self._send_message("interactive", content)

    async def send_meeting_ended_card(
        self,
        topic: str,
        host_name: str | None = None,
        start_time: str | None = None,
        duration: int = 0,
        participants: list[dict] | None = None,
        host_note: str | None = None,
    ) -> dict:
        """Send an intermediate card indicating the meeting ended and recording is being processed."""

        duration_label = f"{duration} мин"
        if duration >= 60:
            hours = duration // 60
            mins = duration % 60
            duration_label = f"{hours} ч" + (f" {mins} мин" if mins else "")

        fields = [
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**📌 Тема:**\n{topic}",
                },
            },
        ]

        if duration:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**⏱ Длительность:**\n{duration_label}",
                },
            })

        if start_time:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**🕐 Начало:**\n{start_time}",
                },
            })

        if host_name:
            host_label = host_name
            if host_note:
                host_label = f"{host_note} ({host_name})"
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**👤 Организатор:**\n{host_label}",
                },
            })

        elements = [{"tag": "div", "fields": fields}]

        if participants and len(participants) > 0:
            participant_lines = []
            for p in participants:
                note = p.get('note', '')
                first_name = p.get('first_name') or p.get('username') or 'Участник'
                if note:
                    participant_lines.append(f"{note} ({first_name})")
                else:
                    participant_lines.append(first_name)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**👥 Участники ({len(participants)}):**\n" + "\n".join(participant_lines),
                },
            })

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "⏳ Запись обрабатывается, результаты появятся автоматически...",
            },
        })

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "✅ Встреча завершена",
                },
                "template": "yellow",
            },
            "elements": elements,
        }

        content = json.dumps(card)
        return await self._send_message("interactive", content)

    async def send_meeting_cancelled_card(
        self,
        topic: str,
        host_name: str | None = None,
        start_time: str | None = None,
        duration: int = 0,
        participants: list[dict] | None = None,
    ) -> dict:
        """Send a card indicating the meeting was cancelled by the organizer."""

        duration_label = f"{duration} мин"
        if duration >= 60:
            hours = duration // 60
            mins = duration % 60
            duration_label = f"{hours} ч" + (f" {mins} мин" if mins else "")

        fields = [
            {
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**📌 Тема:**\n{topic}",
                },
            },
        ]

        if duration:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**⏱ Длительность:**\n{duration_label}",
                },
            })

        if start_time:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**🕐 Запланировано:**\n{start_time}",
                },
            })

        if host_name:
            fields.append({
                "is_short": True,
                "text": {
                    "tag": "lark_md",
                    "content": f"**👤 Организатор:**\n{host_name}",
                },
            })

        elements = [{"tag": "div", "fields": fields}]

        if participants and len(participants) > 0:
            participant_lines = []
            for p in participants:
                note = p.get('note', '')
                first_name = p.get('first_name') or p.get('username') or 'Участник'
                if note:
                    participant_lines.append(f"~~{note} ({first_name})~~")
                else:
                    participant_lines.append(f"~~{first_name}~~")
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**👥 Участники ({len(participants)}):**\n" + "\n".join(participant_lines),
                },
            })

        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "🚫 Встреча отменена организатором.",
            },
        })

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🚫 Встреча отменена",
                },
                "template": "red",
            },
            "elements": elements,
        }

        content = json.dumps(card)
        return await self._send_message("interactive", content)

    async def get_chat_admin_and_owner_ids(self) -> list[str]:
        """Fetch open_ids of chat owner + admins only."""
        token = await self.get_tenant_token()

        async with aiohttp.ClientSession() as session:
            chat_url = f"https://open.feishu.cn/open-apis/im/v1/chats/{self.group_chat_id}"
            async with session.get(
                chat_url,
                params={"user_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                chat_data = await resp.json()
                if chat_data.get("code") != 0:
                    logger.warning(f"Could not fetch chat owner/admins: {chat_data}")
                    return []

        data = chat_data.get("data", {})
        ids: set[str] = set()
        owner_id = data.get("owner_id")
        if owner_id:
            ids.add(owner_id)
        for oid in data.get("user_manager_id_list", []) or []:
            if oid:
                ids.add(oid)

        out = sorted(ids)
        logger.info(f"Fetched {len(out)} admin/owner members for task assignment")
        return out

    async def create_lark_task(
        self,
        title: str,
        description: str | None = None,
        meeting_url: str | None = None,
        meeting_topic: str | None = None,
    ) -> dict:
        """Create a real task in Lark Task system via Task API v2."""
        token = await self.get_tenant_token()

        body: dict = {"summary": title}

        if description:
            body["description"] = description

        if meeting_url or meeting_topic:
            href: dict = {}
            if meeting_url:
                href["url"] = meeting_url
            if meeting_topic:
                href["title"] = meeting_topic
            body["origin"] = {
                "href": href,
                "platform_i18n_name": {
                    "zh_cn": "NC Meeting Bot",
                    "en_us": "NC Meeting Bot",
                },
            }

        # Add only chat owner/admins as assignees
        try:
            member_ids = await self.get_chat_admin_and_owner_ids()
            if member_ids:
                body["members"] = [
                    {"id": oid, "type": "user", "role": "assignee"}
                    for oid in member_ids
                ]
        except Exception as me:
            logger.warning(f"Could not add members to Lark task: {me}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://open.feishu.cn/open-apis/task/v2/tasks",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=body,
            ) as resp:
                data = await resp.json()
                if data.get("code") != 0:
                    logger.error(f"Lark create task error: {data}")
                    raise Exception(f"Failed to create Lark task: {data}")
                task_info = data.get("data", {}).get("task", {})
                logger.info(f"Lark task created: {title} | guid={task_info.get('guid')} | url={task_info.get('url')}")
                return data

    async def send_task_card(
        self,
        meeting_topic: str,
        task_title: str,
        task_description: str | None = None,
        meeting_url: str | None = None,
        lark_task_url: str | None = None,
    ) -> dict:
        """Send an action-item card to the Lark group."""
        elements = []

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**📌 {task_title}**",
            },
        })

        if task_description:
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": task_description,
                },
            })

        elements.append({"tag": "hr"})

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"🎥 Встреча: **{meeting_topic}**",
            },
        })

        actions = []
        if lark_task_url:
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✅ Открыть задачу в Lark"},
                "type": "primary",
                "url": lark_task_url,
            })
        if meeting_url:
            actions.append({
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📄 Открыть встречу"},
                "type": "default",
                "url": meeting_url,
            })

        if actions:
            elements.append({"tag": "action", "actions": actions})

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "✅ Задача по встрече"},
                "template": "orange",
            },
            "elements": elements,
        }

        content = json.dumps(card)
        return await self._send_message("interactive", content)
