// Runtime configuration for the SPA.
//
// The same static export is deployed across environments, so per-deploy
// values are read at runtime from /config.json rather than baked in at build
// time. NEXT_PUBLIC_ env vars, if present at build time, act as fallbacks/
// overrides. This keeps the artifact identical across deploys.
//
// Value sources (CloudFormation outputs):
//   cognitoDomain <- auth stack output  CognitoDomainUrl
//   clientId      <- auth stack output  UserPoolClientId
//   region        <- deploy region (us-east-1)
//   apiBase       <- always '/api' (same-origin, path-routed by the ALB)

export interface AppConfig {
  cognitoDomain: string;
  clientId: string;
  region: string;
  apiBase: string;
}

const ENV_FALLBACK: AppConfig = {
  cognitoDomain: process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? '',
  clientId: process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? '',
  region: process.env.NEXT_PUBLIC_AWS_REGION ?? 'us-east-1',
  apiBase: process.env.NEXT_PUBLIC_API_BASE ?? '/api',
};

let cached: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (cached) {
    return cached;
  }

  let fileConfig: Partial<AppConfig> = {};
  try {
    const res = await fetch('/config.json', { cache: 'no-store' });
    if (res.ok) {
      fileConfig = (await res.json()) as Partial<AppConfig>;
    }
  } catch {
    // Fall back to build-time env values if the file is unavailable.
  }

  cached = {
    cognitoDomain: fileConfig.cognitoDomain || ENV_FALLBACK.cognitoDomain,
    clientId: fileConfig.clientId || ENV_FALLBACK.clientId,
    region: fileConfig.region || ENV_FALLBACK.region,
    apiBase: fileConfig.apiBase || ENV_FALLBACK.apiBase,
  };

  return cached;
}
