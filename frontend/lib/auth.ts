// Client-side OAuth2 Authorization Code + PKCE against Cognito Managed Login.
//
// Google is the only identity provider, so both "login" and "register" start
// the same hosted redirect to Cognito (which then redirects to Google). There
// is no in-app username/password form. The app is a public SPA client with no
// client secret; PKCE protects the code exchange.
//
// Flow:
//   1. login()/register() -> generate PKCE verifier+challenge, stash the
//      verifier in sessionStorage, redirect to the Cognito /oauth2/authorize
//      endpoint with identity_provider=Google.
//   2. Cognito redirects back to the site root with ?code=... . The redirect
//      URI is window.location.origin + '/', matching the CallbackURLs the auth
//      stack registers (${AppUrl}/ and ${AppUrl}/index.html).
//   3. handleRedirectCallback() exchanges the code at /oauth2/token using the
//      stored verifier and stores the tokens in sessionStorage.

import { loadConfig, type AppConfig } from './config';

const VERIFIER_KEY = 'pkce_code_verifier';
const TOKENS_KEY = 'auth_tokens';

export interface AuthTokens {
  accessToken: string;
  idToken: string;
  refreshToken?: string;
  expiresAt: number; // epoch ms
}

interface TokenResponse {
  access_token: string;
  id_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
}

// The redirect URI must be the site root, matching the registered CallbackURLs.
function redirectUri(): string {
  return `${window.location.origin}/`;
}

function base64UrlEncode(bytes: Uint8Array): string {
  let str = '';
  for (const b of bytes) {
    str += String.fromCharCode(b);
  }
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomVerifier(): string {
  const bytes = new Uint8Array(64);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

async function challengeFromVerifier(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return base64UrlEncode(new Uint8Array(digest));
}

async function beginHostedRedirect(config: AppConfig): Promise<void> {
  const verifier = randomVerifier();
  const challenge = await challengeFromVerifier(verifier);
  sessionStorage.setItem(VERIFIER_KEY, verifier);

  const params = new URLSearchParams({
    response_type: 'code',
    client_id: config.clientId,
    redirect_uri: redirectUri(),
    scope: 'openid email profile',
    identity_provider: 'Google',
    code_challenge: challenge,
    code_challenge_method: 'S256',
  });

  window.location.assign(`${config.cognitoDomain}/oauth2/authorize?${params.toString()}`);
}

// Both entry points start the same Google hosted flow.
export async function login(): Promise<void> {
  const config = await loadConfig();
  await beginHostedRedirect(config);
}

export async function register(): Promise<void> {
  const config = await loadConfig();
  await beginHostedRedirect(config);
}

export async function logout(): Promise<void> {
  const config = await loadConfig();
  clearTokens();
  const params = new URLSearchParams({
    client_id: config.clientId,
    logout_uri: redirectUri(),
  });
  window.location.assign(`${config.cognitoDomain}/logout?${params.toString()}`);
}

// Exchange the ?code= present on the current URL for tokens. Returns the tokens
// on success, or null if there is no code to process. Removes the code from the
// address bar afterwards so a reload does not re-trigger the exchange.
export async function handleRedirectCallback(): Promise<AuthTokens | null> {
  const url = new URL(window.location.href);
  const code = url.searchParams.get('code');
  if (!code) {
    return null;
  }

  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  if (!verifier) {
    // No verifier to complete the exchange; clean the URL and bail.
    cleanUrl();
    return null;
  }

  const config = await loadConfig();
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: config.clientId,
    code,
    redirect_uri: redirectUri(),
    code_verifier: verifier,
  });

  const res = await fetch(`${config.cognitoDomain}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });

  sessionStorage.removeItem(VERIFIER_KEY);
  cleanUrl();

  if (!res.ok) {
    throw new Error(`Token exchange failed (${res.status})`);
  }

  const data = (await res.json()) as TokenResponse;
  const tokens: AuthTokens = {
    accessToken: data.access_token,
    idToken: data.id_token,
    refreshToken: data.refresh_token,
    expiresAt: Date.now() + data.expires_in * 1000,
  };
  storeTokens(tokens);
  return tokens;
}

function cleanUrl(): void {
  window.history.replaceState({}, document.title, window.location.pathname);
}

export function storeTokens(tokens: AuthTokens): void {
  sessionStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
}

export function getTokens(): AuthTokens | null {
  const raw = sessionStorage.getItem(TOKENS_KEY);
  if (!raw) {
    return null;
  }
  try {
    const tokens = JSON.parse(raw) as AuthTokens;
    if (tokens.expiresAt && tokens.expiresAt <= Date.now()) {
      clearTokens();
      return null;
    }
    return tokens;
  } catch {
    return null;
  }
}

export function clearTokens(): void {
  sessionStorage.removeItem(TOKENS_KEY);
}

// Call the protected hello endpoint through CloudFront (/api/hello) with a
// Bearer token.
//
// Token choice per endpoint (decide deliberately as more routes are added):
//   - Access token (sent here): carries scopes/groups, not user identity
//     claims. Correct for authorization-only endpoints like /hello that just
//     need to confirm a valid session.
//   - ID token: carries user identity claims (email, name, profile). Prefer it
//     for endpoints that key on who the user is (e.g. future content/progress
//     APIs). The backend currently accepts either, so send the ID token from a
//     dedicated caller for identity-bearing routes rather than defaulting to
//     whichever token the SPA happens to have.
export async function callHello(): Promise<string> {
  const config = await loadConfig();
  const tokens = getTokens();
  if (!tokens) {
    throw new Error('Not authenticated');
  }

  const res = await fetch(`${config.apiBase}/hello`, {
    headers: { Authorization: `Bearer ${tokens.accessToken}` },
  });

  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Request failed (${res.status}): ${text}`);
  }
  return text;
}
