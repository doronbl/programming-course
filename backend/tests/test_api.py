"""Endpoint tests for health and the protected hello route."""

from __future__ import annotations

from tests.conftest import make_token


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_hello_requires_auth(client):
    response = client.get("/api/hello")
    assert response.status_code == 401


def test_hello_with_valid_token(client, rsa_key):
    token = make_token(rsa_key)
    response = client.get("/api/hello", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert "Hello World" in response.text


def test_hello_with_valid_id_token(client, rsa_key):
    token = make_token(rsa_key, token_use="id", aud="test-client-id", client_id=None)
    response = client.get("/api/hello", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert "Hello World" in response.text


def test_hello_invalid_token(client):
    response = client.get(
        "/api/hello", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_hello_expired_token(client, rsa_key):
    token = make_token(rsa_key, exp_offset=-10)
    response = client.get("/api/hello", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_hello_wrong_issuer(client, rsa_key):
    token = make_token(rsa_key, iss="https://evil.example.com/pool")
    response = client.get("/api/hello", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_hello_wrong_client(client, rsa_key):
    token = make_token(rsa_key, client_id="some-other-client")
    response = client.get("/api/hello", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
