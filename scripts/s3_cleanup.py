"""
One-time cleanup: delete S3 files for meetings that no longer exist in the DB.

Usage:
    python s3_cleanup.py          # dry-run (shows what would be deleted)
    python s3_cleanup.py --delete  # actually delete
"""
import argparse
import os
import sys

import asyncpg
import asyncio
import boto3
from botocore.config import Config as BotoConfig
from dotenv import load_dotenv

load_dotenv()

# ── Config from .env ──────────────────────────────────────────────────────────
# Inside Docker the hostname is "postgres"; outside it's "localhost:5434"
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neuro_user:neuro_password@postgres:5432/neuro_connector",
)

S3_ENDPOINT  = os.getenv("S3_ENDPOINT",  "https://s3.twcstorage.ru")
S3_BUCKET    = os.getenv("S3_BUCKET",    "runneurosoft")
S3_ACCESS    = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET    = os.getenv("S3_SECRET_KEY", "")
S3_REGION    = os.getenv("S3_REGION",    "ru-1")


def get_s3():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS,
        aws_secret_access_key=S3_SECRET,
        region_name=S3_REGION,
        config=BotoConfig(signature_version="s3v4"),
    )


def list_s3_meeting_ids(client) -> dict[str, list[str]]:
    """Return {meeting_id_str: [key, ...]} for every folder under meetings/."""
    meetings: dict[str, list[str]] = {}
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="meetings/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]               # meetings/12345678/video.mp4
            parts = key.split("/")
            if len(parts) >= 2 and parts[1]:
                mid = parts[1]
                meetings.setdefault(mid, []).append(key)
    return meetings


async def get_db_meeting_ids() -> set[str]:
    conn = await asyncpg.connect(DB_URL)
    try:
        rows = await conn.fetch("SELECT meeting_id FROM zoom_meetings")
        return {str(r["meeting_id"]) for r in rows}
    finally:
        await conn.close()


async def main(dry_run: bool):
    print("Connecting to DB…")
    db_ids = await get_db_meeting_ids()
    print(f"  {len(db_ids)} meeting(s) in DB")

    print("Listing S3 objects…")
    s3 = get_s3()
    s3_meetings = list_s3_meeting_ids(s3)
    print(f"  {len(s3_meetings)} meeting folder(s) in S3")

    orphaned = {mid: keys for mid, keys in s3_meetings.items() if mid not in db_ids}

    if not orphaned:
        print("\n✅ Nothing to clean up — S3 is in sync with DB.")
        return

    total_files = sum(len(v) for v in orphaned.values())
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Found {len(orphaned)} orphaned folder(s), {total_files} file(s):")
    for mid, keys in sorted(orphaned.items()):
        print(f"  meeting_id={mid}:")
        for k in keys:
            print(f"    - {k}")

    if dry_run:
        print("\nRun with --delete to actually remove these files.")
        return

    print("\nDeleting…")
    deleted = 0
    for mid, keys in sorted(orphaned.items()):
        delete_payload = {"Objects": [{"Key": k} for k in keys]}
        resp = s3.delete_objects(Bucket=S3_BUCKET, Delete=delete_payload)
        errors = resp.get("Errors", [])
        if errors:
            for err in errors:
                print(f"  ERROR {err['Key']}: {err['Message']}")
        deleted += len(keys) - len(errors)
        print(f"  ✓ meeting_id={mid}: {len(keys) - len(errors)} file(s) deleted")

    print(f"\n✅ Done. {deleted}/{total_files} file(s) deleted from S3.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true", help="Actually delete (default: dry-run)")
    args = parser.parse_args()

    asyncio.run(main(dry_run=not args.delete))
