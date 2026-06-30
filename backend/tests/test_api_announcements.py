from fastapi.testclient import TestClient

from backend.api.app import app

client = TestClient(app)


def test_announcements_empty_with_note():
    r = client.get("/api/announcements")
    assert r.status_code == 200
    body = r.json()
    assert body["announcements"] == []
    assert "RAG" in body["note"] or "阶段 5" in body["note"]


def test_announcements_with_fund_code_param():
    r = client.get("/api/announcements", params={"fund_code": "110011", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["announcements"], list)
    assert body["fund_code"] == "110011"
    assert body["limit"] == 5
