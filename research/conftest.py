"""Tests must never read or write the developer's real provider data or budget."""
import pytest


@pytest.fixture(autouse=True)
def isolate_provider_state(monkeypatch,tmp_path):
    # Unit fixtures exercise request contracts without touching a real account.
    # Dedicated native_access tests override this and test the preflight boundary.
    import native_access
    monkeypatch.setattr(native_access,'require',lambda:None)
    monkeypatch.setenv('OUTLOUD_PROVIDER_CACHE',str(tmp_path/'provider-media.sqlite3'))
    monkeypatch.setenv('OUTLOUD_BUDGET_DB',str(tmp_path/'provider-budget.sqlite3'))
