"""
Audio/video transcription service.
Source: mini_app/server.py lines 4900-5400

Contains:
- build_transcription_prompt(participants, ...) -> str
- gather_participant_names(meeting_id, db) -> list[str]
- auto_transcribe_audio(meeting_id, audio_url, db, ...) -> None
- process_uploaded_video(meeting_id, video_path, db, s3, ...) -> None
- upload_video_to_s3(meeting_id, path, s3) -> str
- upload_audio_to_s3(meeting_id, path, s3) -> str

All functions are pure async — no HTTP objects.
TODO: Extract implementations from server.py
"""

import logging

logger = logging.getLogger(__name__)
