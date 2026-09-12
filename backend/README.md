# programming-course backend

FastAPI service (Python 3.12, uvicorn) for the programming-course application.
It exposes a public health endpoint for the ALB and a Cognito-JWT-protected
`/api/hello` endpoint.

## Endpoints

| Method | Path         | Auth            | Purpose                                   |
| ------ | ------------ | --------------- | ----------------------------------------- |
| GET    | `/health`    | Public          | ALB target group health check (HTTP 200). |
| GET    | `/api/hello` | Bearer JWT      | Returns `{"message": "Hello World"}`.     |

### Routing and CloudFront

CloudFront serves the SPA by default and forwards the `/api/*` path pattern to
the ALB **without stripping the `/api` prefix** (see `infra/storage.yaml`).
Application routes are therefore served under `/api` so a same-origin browser
request to `/api/hello` reaches the `hello` handler.

`/health` stays at the root because the ALB target group hits the container
directly (port 8000), not through CloudFront.

## Authentication

Only Cognito-issued tokens are accepted (Google is the sole IdP, federated via
Cognito Managed Login). For any protected request the service:

1. Reads the `Authorization: Bearer <token>` header.
2. Fetches and caches the Cognito user pool's JWKS from
   `<COGNITO_ISSUER>/.well-known/jwks.json`.
3. Verifies the RS256 signature against the matching key, and validates the
   issuer and expiry.
4. Confirms `token_use` is `access` or `id` and that the token was issued for
   `COGNITO_CLIENT_ID` (`client_id` on access tokens, `aud` on id tokens).

Any failure returns HTTP 401.

## Configuration (environment variables)

These names match `infra/compute.yaml` exactly.

| Variable               | Default (if unset)                                              | Description                          |
| ---------------------- | --------------------------------------------------------------- | ------------------------------------ |
| `COGNITO_USER_POOL_ID` | _(empty)_                                                       | Cognito user pool id.                |
| `COGNITO_REGION`       | `us-east-1`                                                     | Region of the user pool.             |
| `COGNITO_CLIENT_ID`    | _(empty)_                                                       | Cognito app client id.               |
| `COGNITO_ISSUER`       | `https://cognito-idp.<region>.amazonaws.com/<pool_id>`          | Token issuer URL.                    |
| `AWS_REGION`           | `us-east-1`                                                     | Region for boto3 clients.            |
| `CONTENT_BUCKET`       | _(empty)_                                                       | S3 bucket with course content.       |
| `PORT`                 | `8000`                                                          | Port uvicorn binds to.               |

## Run locally

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

export COGNITO_USER_POOL_ID=us-east-1_xxxxxxxxx
export COGNITO_CLIENT_ID=your-app-client-id
export CONTENT_BUCKET=course-content-xxxxxxxx

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`GET http://localhost:8000/health` returns `{"status": "ok"}`.

## Build and run the Docker image

```bash
docker build -t course-backend .
docker run --rm -p 8000:8000 \
  -e COGNITO_USER_POOL_ID=us-east-1_xxxxxxxxx \
  -e COGNITO_CLIENT_ID=your-app-client-id \
  -e CONTENT_BUCKET=course-content-xxxxxxxx \
  course-backend
```

The image runs `uvicorn app.main:app --host 0.0.0.0 --port 8000` and includes a
Docker `HEALTHCHECK` that hits `/health`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests -q
```

Tests replace the Cognito JWKS with a locally generated RSA key pair (via
FastAPI `dependency_overrides`), so JWT verification is exercised end-to-end
without network access.

## S3 access

`app/s3.py` provides `list_content_objects` / `get_content_object` helpers that
use the ECS task role's S3 permissions on `CONTENT_BUCKET` (granted in
`infra/compute.yaml`). They demonstrate the wiring for a future content API.
