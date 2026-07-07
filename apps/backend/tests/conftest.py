import os

os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres:testpassword@localhost:5432/taxflow_test"
)
os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi.testclient import TestClient

from taxflow.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def trial_client_row():
    """A minimal client dict shaped like a `clients` table row, for middleware tests."""
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "email": "test@example.com.au",
        "subscription_status": "trialing",
    }
