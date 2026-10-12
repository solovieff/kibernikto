"""Shared S3 client construction: one source of endpoint, credentials, retries and addressing."""

from kibernikto.storage.config import STORAGE_SETTINGS

S3_MAX_ATTEMPTS = 3


def s3_client_kwargs() -> dict[str, object]:
    """Keyword arguments for ``boto3.client('s3', ...)`` / ``aioboto3.Session().client('s3', ...)``."""
    from botocore.config import Config as BotoConfig

    s = STORAGE_SETTINGS
    return {
        "endpoint_url": s.S3_ENDPOINT,
        "region_name": s.S3_REGION,
        "aws_access_key_id": s.S3_ACCESS_KEY,
        "aws_secret_access_key": s.S3_SECRET_KEY,
        "config": BotoConfig(
            retries={"max_attempts": S3_MAX_ATTEMPTS},
            s3={"addressing_style": s.S3_ADDRESSING_STYLE},
            request_checksum_calculation=s.S3_CHECKSUM_CALCULATION,
        ),
    }


async def open_async_client():  # noqa: ANN201 — aiobotocore client type is generated at runtime
    """Open a long-lived aioboto3 S3 client; the caller must ``await client.__aexit__(None, None, None)``."""
    import aioboto3

    return await aioboto3.Session().client("s3", **s3_client_kwargs()).__aenter__()


def head_bucket_sync(bucket: str | None) -> None:
    """Synchronous HEAD bucket for startup validation; raises on any failure."""
    import boto3

    boto3.client("s3", **s3_client_kwargs()).head_bucket(Bucket=bucket)
