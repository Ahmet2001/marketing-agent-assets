const API_BASE = 'https://open.tiktokapis.com/v2';
const TOKEN_URL = 'https://open.tiktokapis.com/v2/oauth/token/';
const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;
// TikTok's chunked upload requires 5-64MB per chunk (last chunk may be
// smaller). This worker currently supports the common single-chunk case.
const MAX_SINGLE_CHUNK_BYTES = 64 * 1024 * 1024;

function requireTiktokConfig(credentials = {}) {
  const clientKey = credentials.clientKey || process.env.TIKTOK_CLIENT_KEY;
  const clientSecret = credentials.clientSecret || process.env.TIKTOK_CLIENT_SECRET;
  const refreshToken = credentials.refreshToken || process.env.TIKTOK_REFRESH_TOKEN;
  const missing = [];
  if (!clientKey) missing.push('TIKTOK_CLIENT_KEY');
  if (!clientSecret) missing.push('TIKTOK_CLIENT_SECRET');
  if (!refreshToken) missing.push('TIKTOK_REFRESH_TOKEN');
  if (missing.length) {
    const error = new Error(`TikTok yayinlama icin .env eksik: ${missing.join(', ')}`);
    error.statusCode = 400;
    throw error;
  }
  return { clientKey, clientSecret, refreshToken };
}

async function getAccessToken({ clientKey, clientSecret, refreshToken }) {
  const response = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Cache-Control': 'no-cache'
    },
    body: new URLSearchParams({
      client_key: clientKey,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: 'refresh_token'
    })
  });
  const data = await response.json();
  if (!response.ok || !data.access_token) {
    const error = new Error(`TikTok token yenileme hatasi: ${data.error_description || data.error || response.statusText}`);
    error.statusCode = 502;
    throw error;
  }
  return data.access_token;
}

async function apiRequest(path, accessToken, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json; charset=UTF-8'
    },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok || data.error?.code && data.error.code !== 'ok') {
    const error = new Error(`TikTok API hatasi: ${data.error?.message || response.statusText}`);
    error.statusCode = response.status;
    throw error;
  }
  return data.data;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForPublishComplete(publishId, accessToken) {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const response = await fetch(`${API_BASE}/post/publish/status/fetch/`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json; charset=UTF-8'
      },
      body: JSON.stringify({ publish_id: publishId })
    });
    const data = await response.json();
    const status = data.data?.status;
    if (status === 'PUBLISH_COMPLETE') return data.data;
    if (status === 'FAILED') {
      const error = new Error(`TikTok yayinlama basarisiz: ${data.data?.fail_reason || 'bilinmeyen hata'}`);
      error.statusCode = 502;
      throw error;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  const error = new Error('TikTok yayin durumu zaman asimina ugradi.');
  error.statusCode = 504;
  throw error;
}

// privacyLevel defaults to SELF_ONLY: apps that haven't passed TikTok's app
// review (see the "App review" section of the Developer Portal submission)
// are restricted to private/draft posts regardless of what's requested here
// -- TikTok's API silently downgrades or rejects PUBLIC_TO_EVERYONE for an
// unaudited app, so defaulting to the always-available option avoids a
// surprise 4xx until the app is actually approved for public posting.
export async function publishVideoToTiktok({
  videoUrl,
  title = '',
  privacyLevel = 'SELF_ONLY',
  disableComment = false,
  disableDuet = false,
  disableStitch = false,
  credentials
}) {
  if (!videoUrl) {
    const error = new Error('videoUrl zorunlu.');
    error.statusCode = 400;
    throw error;
  }
  const config = requireTiktokConfig(credentials);

  const sourceResponse = await fetch(videoUrl);
  if (!sourceResponse.ok || !sourceResponse.body) {
    const error = new Error(`Video kaynagindan indirilemedi: ${sourceResponse.statusText}`);
    error.statusCode = 502;
    throw error;
  }
  const contentLength = Number(sourceResponse.headers.get('content-length') || 0);
  if (!contentLength) {
    const error = new Error('Video kaynagi Content-Length dondurmedi, TikTok yuklemesi icin gerekli.');
    error.statusCode = 502;
    throw error;
  }
  if (contentLength > MAX_SINGLE_CHUNK_BYTES) {
    const error = new Error(
      `Video boyutu (${Math.round(contentLength / 1024 / 1024)}MB) tek parca TikTok yuklemesi icin cok buyuk (limit 64MB). Coklu-parca yukleme henuz desteklenmiyor.`
    );
    error.statusCode = 413;
    throw error;
  }

  const accessToken = await getAccessToken(config);

  const init = await apiRequest('/post/publish/video/init/', accessToken, {
    post_info: {
      title: String(title || '').slice(0, 150),
      privacy_level: privacyLevel,
      disable_comment: disableComment,
      disable_duet: disableDuet,
      disable_stitch: disableStitch
    },
    source_info: {
      source: 'FILE_UPLOAD',
      video_size: contentLength,
      chunk_size: contentLength,
      total_chunk_count: 1
    }
  });

  const videoBuffer = Buffer.from(await sourceResponse.arrayBuffer());
  const uploadResponse = await fetch(init.upload_url, {
    method: 'PUT',
    headers: {
      'Content-Type': 'video/mp4',
      'Content-Range': `bytes 0-${contentLength - 1}/${contentLength}`
    },
    body: videoBuffer
  });
  if (!uploadResponse.ok) {
    const errorBody = await uploadResponse.text();
    const error = new Error(`TikTok video yuklenemedi: ${errorBody}`);
    error.statusCode = uploadResponse.status;
    throw error;
  }

  const finalStatus = await waitForPublishComplete(init.publish_id, accessToken);

  return {
    publishId: init.publish_id,
    publiclyAvailablePostId: finalStatus.publicaly_available_post_id?.[0] || finalStatus.publicly_available_post_id?.[0] || null
  };
}
