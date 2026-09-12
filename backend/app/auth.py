"""Cognito JWT verification.

A Bearer token on a protected request is verified against the Cognito user
pool's JSON Web Key Set (JWKS). Verification checks the RS256 signature, the
issuer, and the expiry. The JWKS is fetched over HTTPS and cached in memory.

The JWKS client is provided through a FastAPI dependency so tests can override
it with a client backed by a known key pair (see tests/conftest.py).
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings


class JwksClient:
    """Fetches and caches Cognito signing keys, and verifies tokens.

    The keys are cached for ``cache_ttl`` seconds. On a cache miss (or an
    unknown ``kid``) the JWKS document is re-fetched.
    """

    def __init__(self, jwks_url: str, cache_ttl: int = 3600) -> None:
        self._jwks_url = jwks_url
        self._cache_ttl = cache_ttl
        self._keys: dict[str, Any] = {}
        self._fetched_at: float = 0.0

    def _refresh(self) -> None:
        response = httpx.get(self._jwks_url, timeout=5.0)
        response.raise_for_status()
        keys = response.json().get("keys", [])
        self._keys = {key["kid"]: key for key in keys}
        self._fetched_at = time.monotonic()

    def _get_signing_key(self, kid: str) -> Any:
        stale = (time.monotonic() - self._fetched_at) > self._cache_ttl
        if kid not in self._keys or stale:
            self._refresh()
        jwk = self._keys.get(kid)
        if jwk is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Signing key not found for token",
            )
        return jwt.PyJWK(jwk).key

    def decode(self, token: str, *, issuer: str, audience: str | None) -> dict[str, Any]:
        """Verify signature/issuer/expiry and return the token claims."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed token",
            ) from exc

        kid = header.get("kid")
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing key id",
            )

        signing_key = self._get_signing_key(kid)
        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=issuer,
                # Cognito access tokens have no 'aud'; the audience is verified
                # separately below against client_id / token_use.
                options={"verify_aud": False},
            )
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from exc

        self._verify_client(claims, audience)
        return claims

    @staticmethod
    def _verify_client(claims: dict[str, Any], audience: str | None) -> None:
        """Confirm the token was issued for our app client.

        Cognito id tokens carry the client id in ``aud``; access tokens carry
        it in ``client_id``. Either is accepted.
        """
        token_use = claims.get("token_use")
        if token_use not in ("access", "id"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unexpected token_use",
            )
        if audience:
            presented = claims.get("client_id") or claims.get("aud")
            if presented != audience:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token not issued for this client",
                )


_jwks_client: JwksClient | None = None


def get_jwks_client(settings: Settings = Depends(get_settings)) -> JwksClient:
    """Return a process-wide JWKS client. Overridable in tests."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = JwksClient(settings.jwks_url)
    return _jwks_client


def get_current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    jwks: JwksClient = Depends(get_jwks_client),
) -> dict[str, Any]:
    """FastAPI dependency that authenticates the request.

    Reads the ``Authorization: Bearer <token>`` header, verifies the token
    against the Cognito JWKS, and returns the decoded claims. Raises 401 on any
    failure.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    return jwks.decode(
        token,
        issuer=settings.cognito_issuer,
        audience=settings.cognito_client_id or None,
    )
