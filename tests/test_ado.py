import pytest

from app.devops import ado_client
from app.devops.ado_client import ZERO, AdoError


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.text = "x" if data else ""

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def fake_env(monkeypatch):
    monkeypatch.setenv("ADO_ORG", "org")
    monkeypatch.setenv("ADO_PROJECT", "proj")
    monkeypatch.setenv("ADO_REPO", "demo-app")
    monkeypatch.setenv("ADO_PAT", "fake-token")


def fake_requests(monkeypatch, response):
    monkeypatch.setattr(ado_client.requests, "request", lambda *a, **kw: response)


def test_repo_id(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(data={"id": "abc-123"}))
    assert ado_client.repo_id() == "abc-123"


def test_branch_head_returns_commit(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(data={"value": [{"objectId": "f" * 40}]}))
    assert ado_client.branch_head() == "f" * 40


def test_branch_head_empty_repo_returns_zero(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(data={"value": []}))
    assert ado_client.branch_head() == ZERO


def test_error_raises_ado_error(monkeypatch):
    fake_requests(monkeypatch, FakeResponse(status_code=401, data={"message": "unauthorized"}))
    with pytest.raises(AdoError):
        ado_client.repo_id()