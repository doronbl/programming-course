'use client';

import { useEffect, useState } from 'react';
import {
  callHello,
  getTokens,
  handleRedirectCallback,
  login,
  logout,
  register,
} from '@/lib/auth';

export default function HomePage() {
  const [authenticated, setAuthenticated] = useState(false);
  const [ready, setReady] = useState(false);
  const [helloResponse, setHelloResponse] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // On load, complete any pending ?code= redirect, then reflect auth state.
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        await handleRedirectCallback();
      } catch (err) {
        if (active) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
      if (active) {
        setAuthenticated(getTokens() !== null);
        setReady(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  async function onCallHello() {
    setError(null);
    setHelloResponse(null);
    try {
      setHelloResponse(await callHello());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  if (!ready) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Programming Course</h1>

      {authenticated ? (
        <>
          <p>You are signed in.</p>
          <div className="actions">
            <button type="button" onClick={onCallHello}>
              Call /hello
            </button>
            <button type="button" onClick={() => void logout()}>
              Log out
            </button>
          </div>
          {helloResponse !== null && (
            <pre aria-label="hello-response">{helloResponse}</pre>
          )}
        </>
      ) : (
        <>
          <p>Sign in with Google to continue.</p>
          <div className="actions">
            <button type="button" onClick={() => void login()}>
              Login with Google
            </button>
            <button type="button" onClick={() => void register()}>
              Register with Google
            </button>
          </div>
        </>
      )}

      {error && <p className="error">{error}</p>}
    </main>
  );
}
