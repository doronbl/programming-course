# Programming Course Frontend

A static-exported Next.js SPA (App Router, client-side rendered only). No SSR,
no Lambda@Edge, no Next.js server runtime. The build produces a plain static
site in `out/`, which a tiny Express `express.static` server (`server.js`)
serves from a container running as an ECS service behind the ALB.

Google is the only login method. Both "Login with Google" and "Register with
Google" start the same Cognito Managed Login hosted redirect using OAuth2
Authorization Code + PKCE. There is no in-app username/password form.

## Prerequisites

- Node.js 22+

## Install and run

```bash
npm ci          # install dependencies
npm run dev     # local dev server at http://localhost:3000
npm run build   # static export -> out/ (contains index.html)
npm run lint     # ESLint (next lint)
npm run typecheck # tsc --noEmit
```

`npm run build` writes a fully static site to `out/`.

## Container

`Dockerfile` is a multi-stage build: stage 1 runs `npm ci && npm run build` to
produce `out/`; stage 2 serves `out/` with `server.js` (Express
`express.static`, not nginx) on port `3000`. On start, `server.js` renders
`/config.json` from environment variables (`COGNITO_DOMAIN`, `COGNITO_CLIENT_ID`,
`AWS_REGION`, `API_BASE`) set by the ECS task definition, so the same image
works across environments. It also exposes `/healthz` and serves `/` (the app
shell) as the ALB target group health check.

## Runtime configuration

Per-deploy values are read at runtime from `/config.json` so the same static
build works across environments. In the container these are rendered from the
environment; for local `npm run dev`/`build`, build-time `NEXT_PUBLIC_*` env
vars act as fallbacks. A sample `public/config.json` ships with placeholder
values:

```json
{
  "cognitoDomain": "https://REPLACE_ME.auth.us-east-1.amazoncognito.com",
  "clientId": "REPLACE_ME_USER_POOL_CLIENT_ID",
  "region": "us-east-1",
  "apiBase": "/api"
}
```

### Where each value comes from (CloudFormation outputs)

| config key      | Source                                                        |
| --------------- | ------------------------------------------------------------- |
| `cognitoDomain` | auth stack output `CognitoDomainUrl` (container env `COGNITO_DOMAIN`) |
| `clientId`      | auth stack output `UserPoolClientId` (container env `COGNITO_CLIENT_ID`) |
| `region`        | deploy region (`us-east-1`)                                   |
| `apiBase`       | always `/api` (same-origin, path-routed by the ALB)           |

The site origin used for OAuth callbacks is `window.location.origin`, which
resolves to the public app domain (`AppUrl`). The auth stack registers callback
URLs `${AppUrl}/` and `${AppUrl}/index.html` and logout URL `${AppUrl}/`, so the
SPA uses the site root (`origin + '/'`) as the `redirect_uri` and processes the
`?code=` on the root page.

Equivalent build-time env fallbacks: `NEXT_PUBLIC_COGNITO_DOMAIN`,
`NEXT_PUBLIC_COGNITO_CLIENT_ID`, `NEXT_PUBLIC_AWS_REGION`,
`NEXT_PUBLIC_API_BASE`.

## How the Managed Login PKCE flow works

1. `login()` / `register()` generate a PKCE `code_verifier` (Web Crypto random
   bytes) and its S256 `code_challenge`, stash the verifier in `sessionStorage`,
   and redirect the browser to:

   ```
   https://<cognitoDomain>/oauth2/authorize
     ?response_type=code
     &client_id=<clientId>
     &redirect_uri=<origin>/
     &scope=openid+email+profile
     &identity_provider=Google
     &code_challenge=<S256(verifier)>
     &code_challenge_method=S256
   ```

2. Cognito redirects to Google, then back to the site root with `?code=...`.

3. On load, `handleRedirectCallback()` exchanges the code at
   `https://<cognitoDomain>/oauth2/token` (`grant_type=authorization_code`,
   public client with no secret, including the stored `code_verifier`) and
   stores the tokens in `sessionStorage`.

4. When authenticated, a single "Call /hello" button fetches `${apiBase}/hello`
   (i.e. `/api/hello`, same-origin through the ALB) with header
   `Authorization: Bearer <accessToken>` and prints the response.

`logout()` clears stored tokens and redirects to
`https://<cognitoDomain>/logout`.

## API path mapping

The ALB HTTPS:443 listener has a `/api/*` rule that (after edge
`authenticate-cognito`) forwards to the backend target group. The `/api` prefix
is NOT stripped, so the backend serves the protected route at `/api/hello`. The
frontend therefore uses `apiBase = '/api'` and calls `${apiBase}/hello`, which
reaches the backend hello handler and returns `Hello World`. Because the SPA and
API share the ALB origin, `/api` is a same-origin relative path.
