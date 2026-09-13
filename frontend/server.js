// Minimal static-file server for the exported Next.js SPA.
//
// The SPA is a fully static export in out/. This server does two things:
//   1. Renders /config.json from environment variables at startup so the same
//      image works across environments (the SPA fetches /config.json at runtime).
//   2. Serves out/ as static files with an SPA fallback to index.html.
//
// Kept intentionally tiny (express.static). Not nginx, no SSR.

const express = require('express');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.env.PORT || '3000', 10);
const OUT_DIR = path.join(__dirname, 'out');

// Render runtime config from the environment into out/config.json. The shape
// matches frontend/lib/config.ts (cognitoDomain, clientId, region, apiBase).
const config = {
  cognitoDomain: process.env.COGNITO_DOMAIN || '',
  clientId: process.env.COGNITO_CLIENT_ID || '',
  region: process.env.AWS_REGION || 'us-east-1',
  apiBase: process.env.API_BASE || '/api',
};
fs.writeFileSync(path.join(OUT_DIR, 'config.json'), JSON.stringify(config, null, 2));

const app = express();

// Health probe target for the ALB frontend target group.
app.get('/healthz', (_req, res) => res.status(200).send('ok'));

// Always serve fresh runtime config.
app.get('/config.json', (_req, res) => {
  res.set('Cache-Control', 'no-store');
  res.type('application/json').send(JSON.stringify(config));
});

// Static assets (trailingSlash export emits directory-style index.html files).
app.use(express.static(OUT_DIR, { extensions: ['html'] }));

// SPA fallback: unknown routes return the app shell so client routing works.
app.use((req, res) => {
  res.sendFile(path.join(OUT_DIR, 'index.html'));
});

app.listen(PORT, () => {
  console.log(`frontend static server listening on ${PORT}`);
});
