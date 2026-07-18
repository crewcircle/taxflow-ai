"""S3-compatible object storage adapter implementing
:class:`taxflow.ports.storage.ObjectStoragePort` (Task B2).

Targets Cloudflare R2 (S3-compatible) today, reading credentials from
``settings.R2_*`` rather than ``os.environ`` so the composition root owns
configuration. The boto3 client is built lazily and memoised: when any of the
account id / access key / secret key is missing the adapter degrades gracefully
(returns ``None`` and never constructs a boto3 client), so ingestion and
retrieval keep working without R2 configured — source PDFs just won't have a
stored copy or a "View original PDF" link until credentials are added.
"""

from __future__ import annotations

import hashlib

from taxflow.config import settings


class S3ObjectStorageAdapter:
    """ObjectStoragePort adapter backed by boto3 against Cloudflare R2."""

    def __init__(self) -> None:
        self._client = None
        self._client_checked = False

    def _get_client(self):
        """Lazily build and memoise the boto3 S3 client.

        Returns ``None`` (without constructing any client) when the R2
        credentials are not fully configured.
        """
        if self._client_checked:
            return self._client
        self._client_checked = True

        account_id = settings.R2_ACCOUNT_ID
        access_key = settings.R2_ACCESS_KEY_ID
        secret_key = settings.R2_SECRET_ACCESS_KEY
        if not (account_id and access_key and secret_key):
            return None

        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        return self._client

    def object_key_for(self, source_url: str) -> str:
        """Deterministic object key for a source URL."""
        return hashlib.sha256(source_url.encode()).hexdigest() + ".pdf"

    def upload_source_pdf(self, source_url: str, content: bytes) -> str | None:
        """Upload a source PDF's raw bytes, keyed by a hash of its URL.

        Returns the object key, or ``None`` if R2 isn't configured or the
        bucket name is missing.
        """
        client = self._get_client()
        bucket = settings.R2_BUCKET_NAME
        if not client or not bucket:
            return None
        object_key = self.object_key_for(source_url)
        client.put_object(
            Bucket=bucket, Key=object_key, Body=content, ContentType="application/pdf"
        )
        return object_key

    def get_signed_url(self, object_key: str) -> str | None:
        """Signed, time-limited URL to view a stored source PDF."""
        client = self._get_client()
        bucket = settings.R2_BUCKET_NAME
        if not client or not bucket:
            return None
        return client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": object_key}, ExpiresIn=3600
        )
