"""S3 helper for the course content bucket.

Demonstrates that the ECS task role (infra/compute.yaml grants ListBucket /
GetObject / PutObject on the content bucket) is wired correctly. Kept minimal;
a future content API will build on this.
"""

from __future__ import annotations

from functools import lru_cache

import boto3

from .config import get_settings


@lru_cache
def _client():
    settings = get_settings()
    return boto3.client("s3", region_name=settings.aws_region)


def list_content_objects(prefix: str = "", max_keys: int = 100) -> list[str]:
    """Return object keys under ``prefix`` in the content bucket."""
    settings = get_settings()
    response = _client().list_objects_v2(
        Bucket=settings.content_bucket,
        Prefix=prefix,
        MaxKeys=max_keys,
    )
    return [item["Key"] for item in response.get("Contents", [])]


def get_content_object(key: str) -> bytes:
    """Return the raw bytes of a single object from the content bucket."""
    settings = get_settings()
    response = _client().get_object(Bucket=settings.content_bucket, Key=key)
    return response["Body"].read()
