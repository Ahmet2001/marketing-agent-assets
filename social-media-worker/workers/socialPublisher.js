import 'dotenv/config';

import { credentialsForJob } from '../services/credentials.js';
import { claimNextJob, failJob, finishJob } from '../services/jobQueue.js';
import { publishCarouselToInstagram, publishReelToInstagram } from '../services/instagramPublish.js';
import { publishVideoToTiktok } from '../services/tiktokPublish.js';
import { publishVideoToYoutube } from '../services/youtubePublish.js';

const pollMs = Math.max(1000, Number(process.env.SOCIAL_PUBLISH_POLL_MS || 5000));
const allowedHosts = String(process.env.ALLOWED_VIDEO_HOSTS || '').split(',').map((item) => item.trim()).filter(Boolean);
let running = false;

function log(message, meta = null) {
  console.log(`[social-publisher] ${message}${meta ? ` ${JSON.stringify(meta)}` : ''}`);
}

function validateHttpsUrl(value, label) {
  const url = new URL(String(value || ''));
  if (url.protocol !== 'https:') throw new Error(`${label} must use HTTPS.`);
  if (allowedHosts.length && !allowedHosts.includes(url.hostname)) {
    throw new Error(`${label} host is not allowed: ${url.hostname}`);
  }
  return url.href;
}

function validatePayload(payload) {
  if (!payload || typeof payload !== 'object') throw new Error('Job payload must be an object.');
  const action = String(payload.action || 'video.publish');
  const caption = String(payload.caption || payload.description || '').trim();
  if (action === 'instagram.carousel') {
    const imageUrls = Array.isArray(payload.imageUrls) ? payload.imageUrls : [];
    if (imageUrls.length < 2 || imageUrls.length > 10) {
      throw new Error('instagram.carousel requires 2 to 10 imageUrls.');
    }
    return {
      action,
      imageUrls: imageUrls.map((url, index) => validateHttpsUrl(url, `imageUrls[${index}]`)),
      platforms: ['instagram'],
      caption
    };
  }
  if (action !== 'video.publish') throw new Error(`Unsupported publish action: ${action}`);
  const videoUrl = validateHttpsUrl(payload.videoUrl, 'videoUrl');
  const platforms = [...new Set(Array.isArray(payload.platforms) ? payload.platforms : [])];
  if (!platforms.length || platforms.some((platform) => !['instagram', 'youtube', 'tiktok'].includes(platform))) {
    throw new Error('platforms must contain one or more of instagram, youtube, tiktok.');
  }
  return {
    action,
    videoUrl,
    platforms,
    title: String(payload.title || '').trim(),
    description: String(payload.description || '').trim(),
    caption,
    privacyStatus: ['private', 'unlisted', 'public'].includes(payload.privacyStatus) ? payload.privacyStatus : 'private'
  };
}

async function publish(platform, payload, credentials) {
  if (payload.action === 'instagram.carousel') {
    return publishCarouselToInstagram({ imageUrls: payload.imageUrls, caption: payload.caption, credentials: credentials.instagram });
  }
  if (platform === 'instagram') return publishReelToInstagram({ videoUrl: payload.videoUrl, caption: payload.caption, credentials: credentials.instagram });
  if (platform === 'youtube') return publishVideoToYoutube({ ...payload, credentials: credentials.youtube });
  const privacyLevel = { public: 'PUBLIC_TO_EVERYONE', private: 'SELF_ONLY', unlisted: 'SELF_ONLY' }[payload.privacyStatus];
  return publishVideoToTiktok({ videoUrl: payload.videoUrl, title: payload.title, privacyLevel, credentials: credentials.tiktok });
}

async function processOne() {
  const job = await claimNextJob();
  if (!job) return false;
  const results = {};
  try {
    const payload = validatePayload(job.payload);
    const credentials = await credentialsForJob(job, payload.platforms);
    for (const platform of payload.platforms) {
      try {
        // Sequential publishing avoids rate-limit bursts and duplicate uploads.
        results[platform] = { status: 'published', ...(await publish(platform, payload, credentials)) };
      } catch (error) {
        results[platform] = { status: 'failed', error: error.message || 'Publishing failed.' };
      }
    }
    const failures = Object.values(results).filter((result) => result.status === 'failed');
    if (failures.length) {
      await failJob({ jobId: job.id, results, error: failures.map((result) => result.error).join(' | ') });
      log('Job completed with errors', { jobId: job.id, results });
    } else {
      await finishJob({ jobId: job.id, results });
      log('Job completed', { jobId: job.id, results });
    }
  } catch (error) {
    await failJob({ jobId: job.id, results, error: error.message });
    log('Job failed', { jobId: job.id, error: error.message });
  }
  return true;
}

async function tick() {
  if (running) return;
  running = true;
  try { while (await processOne()) {} } catch (error) { log('Queue polling failed', { error: error.message }); } finally { running = false; }
}

log('Worker started', { pollMs });
await tick();
setInterval(() => { void tick(); }, pollMs);
