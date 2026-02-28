"""
AI chat and summary generation service.
Source: mini_app/server.py lines 1216-1500, 3977-4100, 4124-4460

Contains:
- generate_summary(transcript_text, db) -> str
- generate_short_summary(transcript_text) -> str
- generate_structured_transcript(vtt_text, ...) -> dict
- parse_vtt(vtt_text) -> list[dict]
- AI chat for meetings and projects

All functions are pure async — no HTTP request/response objects.
TODO: Extract implementations from server.py
"""

import logging

logger = logging.getLogger(__name__)
