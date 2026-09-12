# Programming Course Frontend

A static-exported Next.js SPA (App Router, client-side rendered only). No SSR,
no Lambda@Edge, no server runtime. The build produces a plain static site in
`out/` that is hosted on S3 and served through CloudFront.

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

`npm run build` writes a fully static site to `out/`. Upload the contents of
`out/` (including `config.json`) to the SPA S3 bucket.

## Runtime configuration

Per-deploy values are read at runtime from `public/config.json` so the same
static build works across environments. Build-time `NEXT_PUBLIC_*` env vars act
as fallbacks. A sample `public/config.json` ships with placeholder values:

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
| `cognitoDomain` | auth stack output `CognitoDomainUrl`                          |
| `clientId`      | auth stack output `UserPoolClientId`                          |
| `region`        | deploy region (`us-east-1`)                                   |
| `apiBase`       | always `/api` (same-origin, proxied by CloudFront)            |

The site origin used for OAuth callbacks is `window.location.origin`, which
resolves to the CloudFront domain (storage stack output `AppUrl`). The auth
stack registers callback URLs `${AppUrl}/` and `${AppUrl}/index.html` and logout
URL `${AppUrl}/`, so the app uses the site root (`origin + '/'`) as the
`redirect_uri` and processes the `?code=` on the root page.

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
   (i.e. `/api/hello`, same-origin through CloudFront) with header
   `Authorization: Bearer <accessToken>` and prints the response.

`logout()` clears stored tokens and redirects to
`https://<cognitoDomain>/logout`.

## API path mapping

CloudFront has an ordered cache behavior for `/api/*` that forwards to the ALB
(caching disabled, all viewer headers including `Authorization` forwarded). The
`/api` prefix is NOT stripped, so the backend serves the protected route at
`/api/hello`. The frontend therefore uses `apiBase = '/api'` and calls
`${apiBase}/hello`, which reaches the backend hello handler and returns
`Hello World`.
