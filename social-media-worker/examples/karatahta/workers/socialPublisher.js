import 'dotenv/config';

import { createStorageSignedUrl } from '../services/mediaStore.js';
import { publishReelToInstagram } from '../../../services/instagramPublish.js';
import { publishVideoToYoutube } from '../../../services/youtubePublish.js';
import { publishVideoToTiktok } from '../../../services/tiktokPublish.js';
import { credentialsForJob } from '../../../services/credentials.js';
import {
  claimNextSocialPublishJob,
  failSocialPublishJob,
  finishSocialPublishJob
} from '../services/socialPublishQueue.js';
import { getLessonDetailForUser, getLessonVideoByIdForUser } from '../services/supabaseStore.js';

const pollMs = Math.max(1000, Number(process.env.SOCIAL_PUBLISH_POLL_MS || 5000));
let running = false;

function log(message, meta = null) {
  console.log(`[social-publisher] ${message}${meta ? ` ${JSON.stringify(meta)}` : ''}`);
}

function contentMetadata(detail, job) {
  const topic = String(detail.lesson?.topic || detail.lesson?.title || 'Kara Tahta dersi').trim();
  // YouTube has no separate "post as Short" call -- it classifies an upload
  // as a Short from the file's own aspect ratio/duration, but #Shorts in the
  // title/description is YouTube's own documented signal to make that
  // classification reliable rather than relying on inference alone.
  const isVertical = detail.lesson?.orientation === 'vertical';
  const rawTitle = String(job.title || detail.lesson?.title || topic).trim();
  const title = (isVertical && !/#shorts/i.test(rawTitle) ? `${rawTitle} #Shorts` : rawTitle).slice(0, 100);
  const segmentTitles = (detail.segments || [])
    .map((segment) => String(segment.title || '').trim())
    .filter(Boolean)
    .slice(0, 8);
  const defaultDescription = [
    `Bu derste ${topic} konusu adim adim anlatiliyor.`,
    segmentTitles.length ? `Bolumler:\n${segmentTitles.map((segment) => `• ${segment}`).join('\n')}` : '',
    'Kara Tahta ile hazirlandi.',
    isVertical ? '#Shorts' : ''
  ].filter(Boolean).join('\n\n');
  return {
    title,
    description: String(job.description || defaultDescription).trim(),
    caption: String(job.caption || `Kara Tahta | ${title}\n\n${topic}`).trim()
  };
}

async function processOne() {
  const job = await claimNextSocialPublishJob();
  if (!job) return false;
  log('Yayin isi alindi', { jobId: job.id, videoId: job.video_id });
  let instagramResult = null;
  let youtubeResult = null;
  let tiktokResult = null;
  try {
    const target = await getLessonVideoByIdForUser({ videoId: job.video_id, userId: job.user_id });
    if (!target?.video?.video_storage_path) {
      throw new Error('Railway Bucket videosu bulunamadi.');
    }
    const access = await createStorageSignedUrl({
      bucket: 'videos',
      storagePath: target.video.video_storage_path,
      expiresInSeconds: 3600
    });
    const videoUrl = access.signedUrl;
    const detail = await getLessonDetailForUser({ lessonId: target.lesson.id, userId: job.user_id, messageLimit: 1 });
    const metadata = contentMetadata(detail || { lesson: target.lesson, segments: [] }, job);
    const platform = job.target_platform || 'both';
    const credentials = await credentialsForJob(job, ['instagram', 'youtube', 'tiktok']);
    if (platform === 'instagram' || platform === 'both') {
      try {
        instagramResult = { status: 'published', ...(await publishReelToInstagram({ videoUrl, caption: metadata.caption, credentials: credentials.instagram })) };
      } catch (error) {
        instagramResult = { status: 'failed', error: error.message || 'Instagram yayinlanamadi.' };
      }
    }
    if (platform === 'youtube' || platform === 'both') {
      try {
        youtubeResult = {
          status: 'published',
          ...(await publishVideoToYoutube({
            videoUrl,
            title: metadata.title,
            description: metadata.description,
            privacyStatus: job.privacy_status || 'private',
            credentials: credentials.youtube
          }))
        };
      } catch (error) {
        youtubeResult = { status: 'failed', error: error.message || 'YouTube yayinlanamadi.' };
      }
    }
    if (platform === 'tiktok') {
      try {
        // TikTok apps that haven't cleared app review can only post
        // SELF_ONLY regardless of what's requested; see tiktokPublish.js.
        const privacyLevel = { public: 'PUBLIC_TO_EVERYONE', private: 'SELF_ONLY', unlisted: 'SELF_ONLY' }[job.privacy_status] || 'SELF_ONLY';
        tiktokResult = {
          status: 'published',
          ...(await publishVideoToTiktok({ videoUrl, title: metadata.title, privacyLevel, credentials: credentials.tiktok }))
        };
      } catch (error) {
        tiktokResult = { status: 'failed', error: error.message || 'TikTok yayinlanamadi.' };
      }
    }
    const failures = [instagramResult, youtubeResult, tiktokResult].filter((result) => result?.status === 'failed');
    if (failures.length) {
      await failSocialPublishJob({
        jobId: job.id,
        instagramResult,
        youtubeResult,
        tiktokResult,
        error: failures.map((result) => result.error).join(' | ')
      });
      log('Yayin isi hata ile bitti', { jobId: job.id, instagramResult, youtubeResult, tiktokResult });
    } else {
      await finishSocialPublishJob({ jobId: job.id, instagramResult, youtubeResult, tiktokResult });
      log('Yayin isi tamamlandi', { jobId: job.id, instagramResult, youtubeResult, tiktokResult });
    }
  } catch (error) {
    await failSocialPublishJob({ jobId: job.id, instagramResult, youtubeResult, tiktokResult, error: error.message });
    log('Yayin isi islenemedi', { jobId: job.id, error: error.message });
  }
  return true;
}

async function tick() {
  if (running) return;
  running = true;
  try {
    while (await processOne()) {
      // Drain queued work serially: avoids duplicate requests and rate-limit bursts.
    }
  } catch (error) {
    log('Kuyruk kontrol hatasi', { error: error.message });
  } finally {
    running = false;
  }
}

log('Worker basladi', { pollMs });
await tick();
setInterval(() => { void tick(); }, pollMs);
