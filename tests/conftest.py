import pytest


@pytest.fixture(autouse=True)
def no_live_page_fetch(monkeypatch):
    monkeypatch.setattr("commands.handler.fetch_page_title", lambda url: None)
