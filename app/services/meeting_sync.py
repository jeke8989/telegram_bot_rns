"""
Meeting synchronization service — Zoom polling, reconciliation, startup sync.
Source: mini_app/server.py lines 5429-5907

Contains:
- poll_transcript_later(meeting_id, db, zoom_client, ...) -> None
- sync_single_meeting(meeting, db, zoom_client, ...) -> None
- reconcile_overdue_meetings(db, zoom_client, ...) -> None
- periodic_meeting_reconciliation_loop(db, zoom_client, ...) -> None
- sync_meetings_on_startup(db, zoom_client, ...) -> None
- fix_meeting_durations(db, zoom_client) -> None

TODO: Extract implementations from server.py
"""

import logging

logger = logging.getLogger(__name__)
