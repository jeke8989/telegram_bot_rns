"""
Lark/Feishu notification service.
Source: mini_app/server.py (scattered)

Contains:
- send_lark_recording_card_no_summary(meeting, lark_client, db) -> None
- send_telegram_notification(telegram_id, text, config) -> bool
- get_participants_with_notes(meeting_id, db) -> list[dict]
- format_start_time(start_time_dt) -> str | None
- format_end_time(start_time_dt, duration) -> str | None

TODO: Extract implementations from server.py
"""

import logging

logger = logging.getLogger(__name__)
