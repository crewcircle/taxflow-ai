"""Cloudflare R2 (S3-compatible) storage for original source PDFs.

Requires R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
in the environment. Not yet configured in this project - only a DNS-scoped
CLOUDFLARE_API_TOKEN exists today. Every function here degrades gracefully
(returns None) when those env vars are absent, so ingestion and retrieval
keep working without R2 - source PDFs just won't have a stored copy or a
"View original PDF" link until credentials are added.
"""
import hashlib
import os

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not (account_id and access_key and secret_key):
        return None

    import boto3

    _client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    return _client


def object_key_for(source_url: str) -> str:
    return hashlib.sha256(source_url.encode()).hexdigest() + ".pdf"


def upload_source_pdf(source_url: str, content: bytes) -> str | None:
    """Upload a source PDF's raw bytes, keyed by a hash of its URL.
    Returns the object key, or None if R2 isn't configured or the bucket
    name is missing."""
    client = _get_client()
    bucket = os.environ.get("R2_BUCKET_NAME")
    if not client or not bucket:
        return None
    object_key = object_key_for(source_url)
    client.put_object(Bucket=bucket, Key=object_key, Body=content, ContentType="application/pdf")
    return object_key


def get_source_pdf_url(object_key: str) -> str | None:
    """Signed, time-limited URL to view a stored source PDF."""
    client = _get_client()
    bucket = os.environ.get("R2_BUCKET_NAME")
    if not client or not bucket:
        return None
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": object_key}, ExpiresIn=3600
    )
