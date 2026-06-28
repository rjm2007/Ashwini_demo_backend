import json
import boto3
from ..config import settings


class S3Service:
    """This class wraps S3 operations used by the processing pipeline."""

    def __init__(self) -> None:
        self.client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self.bucket = settings.s3_bucket_name

    async def upload_json(self, key: str, payload: dict) -> None:
        """This function uploads JSON payload to S3."""
        self.client.put_object(Bucket=self.bucket, Key=key, Body=json.dumps(payload).encode("utf-8"))

    async def move_object(self, from_key: str, to_key: str) -> None:
        """This function moves an object by copy and delete operations."""
        self.client.copy_object(Bucket=self.bucket, CopySource=f"{self.bucket}/{from_key}", Key=to_key)
        self.client.delete_object(Bucket=self.bucket, Key=from_key)

    async def download_bytes(self, key: str) -> bytes:
        """Download object body as bytes."""
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    async def download_json(self, key: str) -> dict:
        """Download and parse a JSON object from S3."""
        raw = await self.download_bytes(key)
        return json.loads(raw.decode("utf-8"))
