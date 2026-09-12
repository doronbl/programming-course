"""FastAPI application for the programming-course backend.

Routing note (aligns with infra/storage.yaml + FEAT-003 frontend):
  CloudFront forwards the ``/api/*`` path pattern to the ALB WITHOUT stripping
  the ``/api`` prefix. So protected application routes are served under
  ``/api`` (e.g. ``/api/hello``) to match same-origin browser calls through
  CloudFront.

  The health check (``GET /health``) stays at the root because the ALB target
  group hits the container directly, not through CloudFront.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI

from .auth import get_current_user

app = FastAPI(title="programming-course backend", version="0.1.0")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Public liveness endpoint used by the ALB target group."""
    return {"status": "ok"}


api = APIRouter(prefix="/api")


@api.get("/hello", tags=["hello"])
def hello(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, str]:
    """Protected endpoint. Requires a valid Cognito-issued JWT."""
    return {"message": "Hello World"}


app.include_router(api)
