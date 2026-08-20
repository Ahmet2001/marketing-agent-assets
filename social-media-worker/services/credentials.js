function staticCredentials() {
  return {
    instagram: {
      accessToken: process.env.INSTAGRAM_ACCESS_TOKEN,
      businessAccountId: process.env.INSTAGRAM_BUSINESS_ACCOUNT_ID,
      graphApiVersion: process.env.INSTAGRAM_GRAPH_API_VERSION || 'v21.0'
    },
    youtube: {
      clientId: process.env.YOUTUBE_CLIENT_ID,
      clientSecret: process.env.YOUTUBE_CLIENT_SECRET,
      refreshToken: process.env.YOUTUBE_REFRESH_TOKEN,
      tokenUri: process.env.YOUTUBE_TOKEN_URI || 'https://oauth2.googleapis.com/token'
    },
    tiktok: {
      clientKey: process.env.TIKTOK_CLIENT_KEY,
      clientSecret: process.env.TIKTOK_CLIENT_SECRET,
      refreshToken: process.env.TIKTOK_REFRESH_TOKEN
    }
  };
}

// A credentials provider lets multi-tenant applications keep OAuth tokens in
// their own vault/database. The worker only receives a non-secret credentialRef.
export async function credentialsForJob(job, platforms) {
  const providerUrl = String(process.env.CREDENTIALS_PROVIDER_URL || '').trim();
  if (!providerUrl) return staticCredentials();
  const response = await fetch(providerUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(process.env.CREDENTIALS_PROVIDER_TOKEN ? { 'X-Worker-Token': process.env.CREDENTIALS_PROVIDER_TOKEN } : {})
    },
    body: JSON.stringify({ jobId: job.id, credentialRef: job.payload?.credentialRef || null, platforms })
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data) throw new Error(`Credentials provider failed (${response.status}).`);
  return data.credentials || data;
}
