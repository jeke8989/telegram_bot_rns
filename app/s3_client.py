"""S3-compatible storage client for TWC Storage."""
import io
import logging
import os

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Client:
    def __init__(self):
        self.endpoint = os.getenv("S3_ENDPOINT", "https://s3.twcstorage.ru")
        self.bucket = os.getenv("S3_BUCKET", "runneurosoft")
        self.access_key = os.getenv("S3_ACCESS_KEY", "")
        self.secret_key = os.getenv("S3_SECRET_KEY", "")
        self.region = os.getenv("S3_REGION", "ru-1")
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=BotoConfig(signature_version="s3v4"),
            )
        return self._client

    def upload_video(self, meeting_id: int | str, file_bytes: bytes, fmt: str = "mp4") -> str | None:
        """Upload video bytes to S3 and return the public URL."""
        key = f"meetings/{meeting_id}/video.{fmt}"
        content_type = "video/mp4" if fmt == "mp4" else f"video/{fmt}"
        try:
            client = self._get_client()
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
                ACL="public-read",
            )
            url = f"{self.endpoint}/{self.bucket}/{key}"
            logger.info(f"Meeting {meeting_id}: video uploaded to S3 — {len(file_bytes)} bytes -> {url}")
            return url
        except ClientError as e:
            logger.error(f"Meeting {meeting_id}: S3 upload error: {e}")
            return None
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: unexpected S3 error: {e}")
            return None

    def delete_video(self, meeting_id: int | str, fmt: str = "mp4") -> bool:
        """Delete video from S3."""
        key = f"meetings/{meeting_id}/video.{fmt}"
        try:
            client = self._get_client()
            client.delete_object(Bucket=self.bucket, Key=key)
            logger.info(f"Meeting {meeting_id}: video deleted from S3")
            return True
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: S3 delete error: {e}")
            return False

    _AUDIO_CONTENT_TYPES = {
        "m4a": "audio/mp4",
        "mp4": "audio/mp4",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
    }

    def upload_audio(self, meeting_id: int | str, file_bytes: bytes, fmt: str = "m4a") -> str | None:
        """Upload audio bytes to S3 and return the public URL."""
        key = f"meetings/{meeting_id}/audio.{fmt}"
        content_type = self._AUDIO_CONTENT_TYPES.get(fmt, f"audio/{fmt}")
        try:
            client = self._get_client()
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
                ACL="public-read",
            )
            url = f"{self.endpoint}/{self.bucket}/{key}"
            logger.info(f"Meeting {meeting_id}: audio uploaded to S3 — {len(file_bytes)} bytes -> {url}")
            return url
        except ClientError as e:
            logger.error(f"Meeting {meeting_id}: S3 audio upload error: {e}")
            return None
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: unexpected S3 audio error: {e}")
            return None

    def delete_audio(self, meeting_id: int | str, fmt: str = "m4a") -> bool:
        """Delete audio from S3."""
        key = f"meetings/{meeting_id}/audio.{fmt}"
        try:
            client = self._get_client()
            client.delete_object(Bucket=self.bucket, Key=key)
            logger.info(f"Meeting {meeting_id}: audio deleted from S3")
            return True
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: S3 audio delete error: {e}")
            return False

    def delete_meeting_files(self, meeting_id: int | str) -> int:
        """Delete all S3 objects under meetings/{meeting_id}/ prefix. Returns count of deleted objects."""
        prefix = f"meetings/{meeting_id}/"
        try:
            client = self._get_client()
            deleted = 0
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                objects = page.get("Contents", [])
                if not objects:
                    continue
                delete_payload = {"Objects": [{"Key": obj["Key"]} for obj in objects]}
                client.delete_objects(Bucket=self.bucket, Delete=delete_payload)
                deleted += len(objects)
            if deleted:
                logger.info(f"Meeting {meeting_id}: {deleted} S3 object(s) deleted (prefix={prefix})")
            else:
                logger.debug(f"Meeting {meeting_id}: no S3 objects found under prefix={prefix}")
            return deleted
        except Exception as e:
            logger.error(f"Meeting {meeting_id}: S3 delete_meeting_files error: {e}")
            return 0

    def upload_kp(self, filename: str, file_bytes: bytes) -> str | None:
        """Upload a commercial proposal PDF to S3 and return the public URL."""
        key = f"kp/{filename}"
        try:
            client = self._get_client()
            client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=file_bytes,
                ContentType="application/pdf",
                ACL="public-read",
            )
            url = f"{self.endpoint}/{self.bucket}/{key}"
            logger.info(f"KP uploaded to S3 — {len(file_bytes)} bytes -> {url}")
            return url
        except ClientError as e:
            logger.error(f"KP S3 upload error: {e}")
            return None
        except Exception as e:
            logger.error(f"KP unexpected S3 error: {e}")
            return None

    def check_connection(self) -> bool:
        """Verify S3 connection works."""
        try:
            client = self._get_client()
            client.head_bucket(Bucket=self.bucket)
            logger.info(f"S3 connection OK — bucket '{self.bucket}' accessible")
            return True
        except Exception as e:
            logger.warning(f"S3 connection check failed: {e}")
            return False
