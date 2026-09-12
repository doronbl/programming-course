"""Test fixtures.

A real Cognito JWKS is replaced by a locally generated RSA key pair. The
application's JWKS client dependency is overridden with one whose signing key
is that local public key, so tokens signed here verify exactly the way a real
Cognito token would (RS256 signature + issuer + expiry), without any network
access.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import JwksClient, get_current_user, get_jwks_client
from app.config import Settings, get_settings
from app.main import app

TEST_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_TESTPOOL"
TEST_CLIENT_ID = "test-client-id"
TEST_KID = "test-key-1"


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _StubJwksClient(JwksClient):
    """JWKS client whose signing key is the local test public key."""

    def __init__(self, public_key) -> None:
        super().__init__(jwks_url="http://stub.invalid/jwks.json")
        self._public_key = public_key

    def _get_signing_key(self, kid: str):
        if kid != TEST_KID:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Signing key not found for token",
            )
        return self._public_key


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        cognito_user_pool_id="us-east-1_TESTPOOL",
        cognito_region="us-east-1",
        cognito_client_id=TEST_CLIENT_ID,
        cognito_issuer=TEST_ISSUER,
        aws_region="us-east-1",
        content_bucket="course-content-test",
    )


@pytest.fixture
def client(rsa_key, test_settings):
    stub = _StubJwksClient(rsa_key.public_key())
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_jwks_client] = lambda: stub
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_token(rsa_key, *, token_use: str = "access", exp_offset: int = 3600, **overrides) -> str:
    now = int(time.time())
    claims = {
        "sub": "user-123",
        "iss": TEST_ISSUER,
        "client_id": TEST_CLIENT_ID,
        "token_use": token_use,
        "iat": now,
        "exp": now + exp_offset,
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        rsa_key,
        algorithm="RS256",
        headers={"kid": TEST_KID},
    )
