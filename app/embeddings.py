"""
Embeddings service for project-level RAG chat.

Uses OpenAI text-embedding-3-small (1536 dims) for vectorisation
and tiktoken for token-aware chunking of transcripts.
"""

import os
import logging
from typing import Callable, Awaitable

import tiktoken
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
ENCODING_NAME = "cl100k_base"
MAX_CHUNK_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50


def chunk_text(text: str, max_tokens: int = MAX_CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    """Split *text* into overlapping chunks of roughly *max_tokens* tokens."""
    if not text or not text.strip():
        return []

    enc = tiktoken.get_encoding(ENCODING_NAME)
    tokens = enc.encode(text)

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = start + max_tokens
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        start += max_tokens - overlap

    return chunks


async def generate_embeddings(chunks: list[str]) -> list[list[float]]:
    """Call OpenAI embeddings API for a batch of text chunks."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    client = AsyncOpenAI(api_key=api_key)
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=chunks,
    )
    return [item.embedding for item in response.data]


async def generate_single_embedding(text: str) -> list[float]:
    """Generate embedding for a single query string."""
    results = await generate_embeddings([text])
    return results[0]


async def embed_meeting_for_project(db, project_id: int, zoom_meeting_db_id: int):
    """Chunk the meeting transcript and store embeddings enriched with project/meeting metadata."""
    meeting = await db.get_zoom_meeting_by_db_id(zoom_meeting_db_id)
    if not meeting:
        logger.warning(f"Meeting db_id={zoom_meeting_db_id} not found, skipping embedding")
        return

    project = await db.get_project_by_id(project_id)

    meeting_topic = meeting.get("topic") or "Без названия"
    host_name = meeting.get("host_name") or ""
    project_name = project.get("name", "") if project else ""
    project_desc = project.get("description", "") if project else ""

    transcript = meeting.get("transcript_text") or ""
    summary = meeting.get("summary") or ""
    text = f"{summary}\n\n{transcript}".strip()
    if not text:
        logger.info(f"No text to embed for meeting db_id={zoom_meeting_db_id}")
        return

    header_parts = [f"Проект: {project_name}"]
    if project_desc:
        header_parts.append(f"Описание проекта: {project_desc}")
    header_parts.append(f"Встреча: {meeting_topic}")
    if host_name:
        header_parts.append(f"Организатор: {host_name}")
    metadata_header = "\n".join(header_parts)

    chunks = chunk_text(text)
    if not chunks:
        return

    enriched_chunks = [f"{metadata_header}\n\n{chunk}" for chunk in chunks]

    logger.info(
        f"Generating {len(enriched_chunks)} embeddings for "
        f"project '{project_name}' (id={project_id}), meeting '{meeting_topic}' (db_id={zoom_meeting_db_id})"
    )
    embeddings = await generate_embeddings(enriched_chunks)

    records = [
        {"chunk_index": i, "chunk_text": enriched, "embedding": e}
        for i, (enriched, e) in enumerate(zip(enriched_chunks, embeddings))
    ]
    await db.save_embeddings(project_id, zoom_meeting_db_id, records)
    logger.info(f"Embeddings saved for project {project_id}, meeting {zoom_meeting_db_id}")


async def reembed_all_project_meetings(db, project_id: int):
    """Re-generate embeddings for every meeting in a project (e.g. after project rename)."""
    meetings = await db.get_project_meetings(project_id)
    if not meetings:
        logger.info(f"No meetings in project {project_id}, nothing to re-embed")
        return
    for m in meetings:
        try:
            await embed_meeting_for_project(db, project_id, m["db_id"])
        except Exception as e:
            logger.error(f"Failed to re-embed meeting {m['db_id']} for project {project_id}: {e}")
