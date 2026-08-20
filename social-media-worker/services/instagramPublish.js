const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

function requireInstagramConfig(credentials = {}) {
  const accessToken = credentials.accessToken || process.env.INSTAGRAM_ACCESS_TOKEN;
  const businessAccountId = credentials.businessAccountId || process.env.INSTAGRAM_BUSINESS_ACCOUNT_ID;
  const missing = [];
  if (!accessToken) missing.push('INSTAGRAM_ACCESS_TOKEN');
  if (!businessAccountId) missing.push('INSTAGRAM_BUSINESS_ACCOUNT_ID');
  if (missing.length) {
    const error = new Error(`Instagram yayinlama icin .env eksik: ${missing.join(', ')}`);
    error.statusCode = 400;
    throw error;
  }
  return { accessToken, businessAccountId, graphApiVersion: credentials.graphApiVersion || process.env.INSTAGRAM_GRAPH_API_VERSION || 'v21.0' };
}

async function graphRequest(graphApiVersion, requestPath, { method = 'GET', body = null } = {}) {
  const response = await fetch(`https://graph.instagram.com/${graphApiVersion}${requestPath}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    const error = new Error(`Instagram Graph API hatasi: ${data.error?.message || response.statusText}`);
    error.statusCode = response.status;
    throw error;
  }
  return data;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForContainerReady(containerId, accessToken, graphApiVersion) {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const status = await graphRequest(graphApiVersion, `/${containerId}?fields=status_code&access_token=${accessToken}`);
    if (status.status_code === 'FINISHED') return;
    if (status.status_code === 'ERROR') {
      const error = new Error('Instagram video isleme basarisiz oldu.');
      error.statusCode = 502;
      throw error;
    }
    await sleep(POLL_INTERVAL_MS);
  }
  const error = new Error('Instagram video isleme zaman asimina ugradi.');
  error.statusCode = 504;
  throw error;
}

export async function publishReelToInstagram({ videoUrl, caption = '', credentials }) {
  if (!videoUrl) {
    const error = new Error('videoUrl zorunlu.');
    error.statusCode = 400;
    throw error;
  }
  const { accessToken, businessAccountId, graphApiVersion } = requireInstagramConfig(credentials);

  const container = await graphRequest(graphApiVersion, `/${businessAccountId}/media`, {
    method: 'POST',
    body: { media_type: 'REELS', video_url: videoUrl, caption, access_token: accessToken }
  });

  await waitForContainerReady(container.id, accessToken, graphApiVersion);

  const published = await graphRequest(graphApiVersion, `/${businessAccountId}/media_publish`, {
    method: 'POST',
    body: { creation_id: container.id, access_token: accessToken }
  });

  let permalink = null;
  try {
    const permalinkData = await graphRequest(graphApiVersion, `/${published.id}?fields=permalink&access_token=${accessToken}`);
    permalink = permalinkData.permalink || null;
  } catch {
    // best-effort only
  }

  return { mediaId: published.id, permalink };
}

async function createCarouselItemContainer({ imageUrl, accessToken, businessAccountId, graphApiVersion }) {
  const container = await graphRequest(graphApiVersion, `/${businessAccountId}/media`, {
    method: 'POST',
    body: { image_url: imageUrl, is_carousel_item: true, access_token: accessToken }
  });
  return container.id;
}

// "Slide show" post: 2-10 JPEG images published as a single Instagram
// carousel (e.g. a "Kart" session's stills). Each image must already be
// reachable at a public https URL -- convertPngBufferToJpeg + a signed
// storage URL upstream, since Instagram only accepts JPEG here.
export async function publishCarouselToInstagram({ imageUrls, caption = '', credentials }) {
  const urls = (Array.isArray(imageUrls) ? imageUrls : []).filter(Boolean);
  if (urls.length < 2) {
    const error = new Error('Carousel icin en az 2 gorsel gerekli.');
    error.statusCode = 400;
    throw error;
  }
  if (urls.length > 10) {
    const error = new Error('Instagram carousel en fazla 10 gorsel destekler.');
    error.statusCode = 400;
    throw error;
  }
  const { accessToken, businessAccountId, graphApiVersion } = requireInstagramConfig(credentials);

  const childIds = [];
  for (const imageUrl of urls) {
    // Sequential on purpose: each child container must exist before the
    // parent carousel container references it, and this order becomes the
    // published slide order.
    // eslint-disable-next-line no-await-in-loop
    const id = await createCarouselItemContainer({ imageUrl, accessToken, businessAccountId, graphApiVersion });
    childIds.push(id);
  }

  const container = await graphRequest(graphApiVersion, `/${businessAccountId}/media`, {
    method: 'POST',
    body: { media_type: 'CAROUSEL', children: childIds, caption, access_token: accessToken }
  });

  await waitForContainerReady(container.id, accessToken, graphApiVersion);

  const published = await graphRequest(graphApiVersion, `/${businessAccountId}/media_publish`, {
    method: 'POST',
    body: { creation_id: container.id, access_token: accessToken }
  });

  let permalink = null;
  try {
    const permalinkData = await graphRequest(graphApiVersion, `/${published.id}?fields=permalink&access_token=${accessToken}`);
    permalink = permalinkData.permalink || null;
  } catch {
    // best-effort only
  }

  return { mediaId: published.id, permalink };
}
