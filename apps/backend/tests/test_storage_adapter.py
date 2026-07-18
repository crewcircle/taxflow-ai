"""Tests for the S3/R2 ObjectStoragePort adapter (Task B2).

Two regimes:

* **Unconfigured** (empty ``R2_*`` settings): ``upload_source_pdf`` /
  ``get_signed_url`` return ``None`` and NO boto3 client is ever constructed
  (graceful degradation).
* **Configured** (fake ``R2_*`` settings, ``boto3.client`` monkeypatched to a
  ``MagicMock``): ``put_object`` is called with the sha256-hashed key and
  ``ContentType="application/pdf"``; ``generate_presigned_url`` is called with
  ``ExpiresIn=3600`` and the right ``Bucket``/``Key``.
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import pytest

import taxflow.providers as providers
from taxflow.adapters.storage.s3 import S3ObjectStorageAdapter
from taxflow.config import settings
from taxflow.ports.storage import ObjectStoragePort


SOURCE_URL = "https://ato.gov.au/law/view/document?docid=TR20204"
EXPECTED_KEY = hashlib.sha256(SOURCE_URL.encode()).hexdigest() + ".pdf"


@pytest.fixture(autouse=True)
def _reset_providers():
    """Clear the memoised adapter before and after each test."""
    providers.reset_providers()
    yield
    providers.reset_providers()


@pytest.fixture
def clear_r2(monkeypatch):
    """Empty R2 credentials (unconfigured regime)."""
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "", raising=False)
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "", raising=False)
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "", raising=False)
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "", raising=False)


@pytest.fixture
def fake_r2(monkeypatch):
    """Fake R2 credentials + a mocked boto3.client (configured regime)."""
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", "acct123", raising=False)
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", "AKIAFAKE", raising=False)
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", "secretfake", raising=False)
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", "taxflow-sources", raising=False)

    fake_client = MagicMock(name="boto3_s3_client")
    fake_client.generate_presigned_url.return_value = "https://signed.example/pdf"
    fake_boto3_client = MagicMock(name="boto3.client", return_value=fake_client)
    # boto3 is imported lazily inside _get_client; patch the module attribute.
    import boto3

    monkeypatch.setattr(boto3, "client", fake_boto3_client)
    return fake_boto3_client, fake_client


# --- protocol conformance ----------------------------------------------------
def test_adapter_satisfies_port():
    assert isinstance(S3ObjectStorageAdapter(), ObjectStoragePort)


def test_object_key_for_is_sha256_pdf():
    adapter = S3ObjectStorageAdapter()
    assert adapter.object_key_for(SOURCE_URL) == EXPECTED_KEY


# --- unconfigured regime: graceful degradation, no client built --------------
def test_upload_returns_none_and_builds_no_client_when_unconfigured(clear_r2, monkeypatch):
    import boto3

    fake_boto3_client = MagicMock(name="boto3.client")
    monkeypatch.setattr(boto3, "client", fake_boto3_client)

    adapter = S3ObjectStorageAdapter()
    assert adapter.upload_source_pdf(SOURCE_URL, b"%PDF-1.4") is None
    fake_boto3_client.assert_not_called()


def test_signed_url_returns_none_and_builds_no_client_when_unconfigured(clear_r2, monkeypatch):
    import boto3

    fake_boto3_client = MagicMock(name="boto3.client")
    monkeypatch.setattr(boto3, "client", fake_boto3_client)

    adapter = S3ObjectStorageAdapter()
    assert adapter.get_signed_url(EXPECTED_KEY) is None
    fake_boto3_client.assert_not_called()


# --- configured regime: boto3 calls with the right params --------------------
def test_upload_calls_put_object_with_hashed_key(fake_r2):
    fake_boto3_client, fake_client = fake_r2
    adapter = S3ObjectStorageAdapter()

    key = adapter.upload_source_pdf(SOURCE_URL, b"%PDF-1.4 bytes")

    assert key == EXPECTED_KEY
    fake_boto3_client.assert_called_once()
    _, kwargs = fake_boto3_client.call_args
    assert kwargs["endpoint_url"] == "https://acct123.r2.cloudflarestorage.com"
    assert kwargs["region_name"] == "auto"
    fake_client.put_object.assert_called_once_with(
        Bucket="taxflow-sources",
        Key=EXPECTED_KEY,
        Body=b"%PDF-1.4 bytes",
        ContentType="application/pdf",
    )


def test_signed_url_calls_generate_presigned_url_with_3600(fake_r2):
    _, fake_client = fake_r2
    adapter = S3ObjectStorageAdapter()

    url = adapter.get_signed_url(EXPECTED_KEY)

    assert url == "https://signed.example/pdf"
    fake_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "taxflow-sources", "Key": EXPECTED_KEY},
        ExpiresIn=3600,
    )


def test_client_is_memoised_across_calls(fake_r2):
    fake_boto3_client, _ = fake_r2
    adapter = S3ObjectStorageAdapter()

    adapter.upload_source_pdf(SOURCE_URL, b"x")
    adapter.get_signed_url(EXPECTED_KEY)

    # Lazy client built exactly once despite two operations.
    fake_boto3_client.assert_called_once()


# --- shim delegation ---------------------------------------------------------
def test_r2_shim_delegates_to_port(fake_r2):
    from taxflow.services.storage import r2

    assert r2.object_key_for(SOURCE_URL) == EXPECTED_KEY
    assert r2.upload_source_pdf(SOURCE_URL, b"bytes") == EXPECTED_KEY
    assert r2.get_source_pdf_url(EXPECTED_KEY) == "https://signed.example/pdf"


def test_r2_shim_returns_none_when_unconfigured(clear_r2):
    from taxflow.services.storage import r2

    assert r2.upload_source_pdf(SOURCE_URL, b"bytes") is None
    assert r2.get_source_pdf_url(EXPECTED_KEY) is None
