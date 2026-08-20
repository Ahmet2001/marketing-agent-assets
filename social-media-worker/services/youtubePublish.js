const UPLOAD_INIT_URL = 'https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status';

function requireYoutubeConfig(credentials = {}) {
  const clientId = credentials.clientId || process.env.YOUTUBE_CLIENT_ID;
  const clientSecret = credentials.clientSecret || process.env.YOUTUBE_CLIENT_SECRET;
  const refreshToken = credentials.refreshToken || process.env.YOUTUBE_REFRESH_TOKEN;
  const tokenUri = credentials.tokenUri || process.env.YOUTUBE_TOKEN_URI || 'https://oauth2.googleapis.com/token';
  const missing = [];
  if (!clientId) missing.push('YOUTUBE_CLIENT_ID');
  if (!clientSecret) missing.push('YOUTUBE_CLIENT_SECRET');
  if (!refreshToken) missing.push('YOUTUBE_REFRESH_TOKEN');
  if (missing.length) {
    const error = new Error(`YouTube yayinlama icin .env eksik: ${missing.join(', ')}`);
    error.statusCode = 400;
    throw error;
  }
  return { clientId, clientSecret, refreshToken, tokenUri };
}

async function getAccessToken({ clientId, clientSecret, refreshToken, tokenUri }) {
  const response = await fetch(tokenUri, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: 'refresh_token'
    })
  });
  const data = await response.json();
  if (!response.ok || !data.access_token) {
    const error = new Error(`YouTube token yenileme hatasi: ${data.error_description || data.error || response.statusText}`);
    error.statusCode = 502;
    throw error;
  }
  return data.access_token;
}

export async function publishVideoToYoutube({
  videoUrl,
  title,
  description = '',
  privacyStatus = 'private',
  categoryId = '27',
  credentials
}) {
  if (!videoUrl) {
    const error = new Error('videoUrl zorunlu.');
    error.statusCode = 400;
    throw error;
  }
  if (!title) {
    const error = new Error('title zorunlu.');
    error.statusCode = 400;
    throw error;
  }

  const config = requireYoutubeConfig(credentials);

  const sourceResponse = await fetch(videoUrl);
  if (!sourceResponse.ok || !sourceResponse.body) {
    const error = new Error(`Video kaynagindan indirilemedi: ${sourceResponse.statusText}`);
    error.statusCode = 502;
    throw error;
  }
  const contentLength = sourceResponse.headers.get('content-length');
  if (!contentLength) {
    const error = new Error('Video kaynagi Content-Length dondurmedi, YouTube resumable upload icin gerekli.');
    error.statusCode = 502;
    throw error;
  }

  const accessToken = await getAccessToken(config);

  const initResponse = await fetch(UPLOAD_INIT_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json; charset=UTF-8',
      'X-Upload-Content-Type': 'video/mp4',
      'X-Upload-Content-Length': contentLength
    },
    body: JSON.stringify({
      snippet: { title, description, categoryId },
      status: { privacyStatus }
    })
  });

  if (!initResponse.ok) {
    const errorBody = await initResponse.text();
    const error = new Error(`YouTube yukleme oturumu baslatilamadi: ${errorBody}`);
    error.statusCode = initResponse.status;
    throw error;
  }

  const uploadUrl = initResponse.headers.get('location');
  if (!uploadUrl) {
    const error = new Error('YouTube yukleme oturumu icin Location header alinamadi.');
    error.statusCode = 502;
    throw error;
  }

  const uploadResponse = await fetch(uploadUrl, {
    method: 'PUT',
    headers: {
      'Content-Type': 'video/mp4',
      'Content-Length': contentLength
    },
    duplex: 'half',
    body: sourceResponse.body
  });

  const uploadData = await uploadResponse.json();
  if (!uploadResponse.ok || !uploadData.id) {
    const error = new Error(`YouTube video yuklenemedi: ${uploadData.error?.message || uploadResponse.statusText}`);
    error.statusCode = uploadResponse.status;
    throw error;
  }

  return {
    videoId: uploadData.id,
    url: `https://www.youtube.com/watch?v=${uploadData.id}`
  };
}
