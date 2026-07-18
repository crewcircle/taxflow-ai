"""Nightly cleanup for the shared public demo account so query/document
history doesn't accumulate indefinitely or leak between visitors."""
from taxflow.providers import get_relational_data


def reset_demo_data() -> None:
    get_relational_data().demo_reset.reset_demo_rows()
