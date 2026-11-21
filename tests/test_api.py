from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from outloud_api.main import create_app

TOKEN = "outloud-development-test-token-123456789"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'workspace.sqlite3'}", TOKEN)
    with TestClient(app, headers=HEADERS) as client:
        yield client


def project(client, name="Example"):
    response = client.post("/v1/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


def draft(client, project_id):
    response = client.post(f"/v1/projects/{project_id}/drafts",
                           json={"title": "An original story", "format": "X post", "body": "First version"})
    assert response.status_code == 201
    return response.json()


def test_auth_and_honest_capabilities(client):
    assert client.get("/health", headers={"Authorization": ""}).status_code == 200
    for token in ["", "Bearer wrong", b"Bearer " + ("é" * 35).encode("utf-8")]:
        assert client.get("/v1/projects", headers={"Authorization": token}).status_code == 401
    data = client.get("/v1/capabilities").json()
    assert data["projects"] and data["drafts"]
    assert not any(data[name] for name in ["live_discovery", "generation", "billing", "cloud_identity"])


def test_project_boundaries(client):
    first, second = project(client, "First"), project(client, "Second")
    created = draft(client, first["id"])
    assert client.get(f"/v1/projects/{second['id']}/drafts").json() == []
    assert client.get(f"/v1/projects/{first['id']}/drafts").json()[0]["id"] == created["id"]


def test_stale_edit_cannot_overwrite_newer_draft(client):
    created = draft(client, project(client)["id"])
    route = f"/v1/drafts/{created['id']}"
    payload = {"title": "Edited", "body": "Second version", "expected_revision": 1}
    updated = client.put(route, json=payload)
    assert updated.status_code == 200 and updated.json()["revision"] == 2
    stale = client.put(route, json={**payload, "body": "Stale replacement"})
    assert stale.status_code == 409
    stored = client.get(f"/v1/projects/{created['project_id']}/drafts").json()[0]
    assert stored["body"] == "Second version"


def test_draft_deletion(client):
    created = draft(client, project(client)["id"])
    assert client.delete(f"/v1/drafts/{created['id']}").status_code == 204
    assert client.delete(f"/v1/drafts/{created['id']}").status_code == 404
    assert client.get(f"/v1/projects/{created['project_id']}/drafts").json() == []


def test_missing_parent_and_validation(client):
    assert client.post(f"/v1/projects/{uuid4()}/drafts",
                       json={"title": "Draft", "format": "X post"}).status_code == 404
    assert client.post("/v1/projects", json={"name": "   "}).status_code == 422
    assert client.post("/v1/projects", json={"name": "Test", "brand_color": "invalid"}).status_code == 422
    parent = project(client)
    assert client.post(f"/v1/projects/{parent['id']}/drafts",
                       json={"title": "Draft", "format": "unsupported"}).status_code == 422


def test_persistence_across_restarts(tmp_path):
    url = f"sqlite:///{tmp_path / 'persistent.sqlite3'}"
    with TestClient(create_app(url, TOKEN), headers=HEADERS) as first:
        created = project(first, "Persisted")
        saved = draft(first, created["id"])
    with TestClient(create_app(url, TOKEN), headers=HEADERS) as second:
        assert second.get("/v1/projects").json()[0]["id"] == created["id"]
        assert second.get(f"/v1/projects/{created['id']}/drafts").json()[0]["id"] == saved["id"]


def test_startup_requires_configured_token(tmp_path):
    with pytest.raises(RuntimeError, match="OUTLOUD_DEV_TOKEN"):
        with TestClient(create_app(f"sqlite:///{tmp_path / 'invalid.sqlite3'}", "")):
            pass
