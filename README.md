# programming-course

A course for learning how to program. The eventual product organizes content as
hierarchical sections and lectures: a baseline common to all learners, then
per-language sections, with per-user progress tracking.

> **Scope of this pass.** This repository currently delivers **scaffolding and
> source plus CloudFormation templates**, not a live deployment. Nothing here is
> deployed for you. The product features above (hierarchical sections/lectures,
> baseline + per-language content, user progress tracking) are **out of scope**
> for this pass. Voice / Nova Sonic / Polly and any admin UI are also out of
> scope. Course content is uploaded to S3 out-of-band by the operator.

## Monorepo layout

| Directory   | Contents |
|-------------|----------|
| `infra/`    | CloudFormation templates (one per logical stack) plus `infra/README.md`. Provisions VPC + ALB, REGIONAL WAF, Cognito, S3 + CloudFront, and ECS Fargate compute. |
| `backend/`  | FastAPI service (Python 3.12, uvicorn) in a Docker image. Public `/health` for ALB checks and a Cognito-JWT-protected `/api/hello`. |
| `frontend/` | Static-exported Next.js SPA (client-side rendered). Google-only login via Cognito Managed Login, and a button that calls `/api/hello`. |

Deployment procedure and every deploy-time parameter live in **[DEPLOY.md](DEPLOY.md)**.
Per-stack parameter tables and cross-stack exports live in
**[infra/README.md](infra/README.md)**.

## Architecture overview

- **Region:** `us-east-1`. All AWS resources are repeatable and managed with
  CloudFormation.
- **Login (Google only):** Google is the sole identity provider, federated
  through Cognito. Both "register" and "login" start the same Cognito **Managed
  Login** hosted redirect using OAuth2 Authorization Code + PKCE. There is no
  in-app username/password form and no Cognito-native users.
- **Backend:** an ECS **Fargate SPOT** service running the FastAPI container in
  private subnets, behind an internet-facing **Application Load Balancer**. The
  ALB target group health-checks the container at `/health` on port `8000`.
- **Edge / CDN:** a single **CloudFront** distribution serves the SPA from a
  private S3 bucket (via Origin Access Control) by default, and proxies the
  `/api/*` path pattern to the ALB with **caching disabled** (all viewer
  headers, including `Authorization`, are forwarded). The `/api` prefix is not
  stripped, so the backend serves protected routes under `/api`.
- **Content storage:** a private S3 bucket named `course-content-<suffix>`
  (suffix derived from the stack id so the name is repeatable per stack and
  unique across deployments). The ECS task role has list/get/put access to it.
- **Protection:** a **REGIONAL** WAFv2 WebACL (AWS common rule set, known bad
  inputs, and a rate-based rule) is associated with the ALB.

```
Browser
  │
  ▼
CloudFront ──(default, cached)──► S3 SPA bucket (private, via OAC)
  │
  └──(/api/*, caching disabled)──► ALB ──► ECS Fargate SPOT (FastAPI :8000)
                                    ▲                    │
                            REGIONAL WAF          S3 content bucket
                                                 (course-content-<suffix>)

Cognito Managed Login (Google IdP, OAuth2 code + PKCE) issues JWTs the backend
verifies against the Cognito JWKS on every protected request.
```

## Shared values (kept consistent across infra, backend, frontend)

- Container port: **8000** (`infra/network.yaml` target group + `infra/compute.yaml`
  container/`PORT` + `backend/Dockerfile` + uvicorn).
- ALB health check path: **/health** (`infra/network.yaml`), served at the root
  by `backend/app/main.py`.
- CloudFront API path pattern **/api/\*** (`infra/storage.yaml`) maps to the
  backend route **/api/hello** (`backend/app/main.py`); the frontend calls
  `/api/hello` (`frontend/lib`).
- Content bucket name pattern **course-content-\<suffix\>** (`infra/storage.yaml`),
  consumed by the backend `CONTENT_BUCKET` env var.
- Backend env vars in `infra/compute.yaml`
  (`COGNITO_USER_POOL_ID`, `COGNITO_REGION`, `COGNITO_CLIENT_ID`,
  `COGNITO_ISSUER`, `AWS_REGION`, `CONTENT_BUCKET`, `PORT`) match
  `backend/app/config.py`; the frontend config keys (`clientId`,
  `cognitoDomain`, `region`, `apiBase`) map to the auth and storage stack
  outputs.

## Component guides

- Deploy end to end: **[DEPLOY.md](DEPLOY.md)**
- Infrastructure details: **[infra/README.md](infra/README.md)**
- Backend service: **[backend/README.md](backend/README.md)**
- Frontend SPA: **[frontend/README.md](frontend/README.md)**
