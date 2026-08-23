import { readRailwayObjectText, writeRailwayObjectText, railwayMediaConfigured } from './railwayContentStore.js';
import { getSchedulerJob } from './schedulerStore.js';

const POOL_BUCKET = 'system';
const POOL_PATH = 'content_pool.txt';

function requireBucket() {
  if (!railwayMediaConfigured) {
    const error = new Error('Content pool bir bucket gerektirir (MEDIA_S3_* ayarlarini girin).');
    error.statusCode = 400;
    throw error;
  }
}

export async function readContentPool() {
  requireBucket();
  let text;
  try {
    text = await readRailwayObjectText({ bucket: POOL_BUCKET, storagePath: POOL_PATH });
  } catch (error) {
    if (error?.name === 'NoSuchKey' || error?.$metadata?.httpStatusCode === 404) {
      return [];
    }
    throw error;
  }
  return text.split('\n').map((line) => line.trim()).filter(Boolean);
}

export async function writeContentPool(text) {
  requireBucket();
  await writeRailwayObjectText({ bucket: POOL_BUCKET, storagePath: POOL_PATH, text: String(text || '') });
}

// Sequential, wrap-around pick: each scheduled job_type tracks its own
// cursor into the pool (scheduler_jobs.content_pool_cursor) so
// cards_carousel and lesson_video progress through the same idea list
// independently.
export async function pickNextContentPoolItem(jobType) {
  const items = await readContentPool();
  if (!items.length) {
    const error = new Error('content_pool.txt bos veya bulunamadi.');
    error.statusCode = 422;
    throw error;
  }
  const job = await getSchedulerJob(jobType);
  const cursor = Number(job?.content_pool_cursor) || 0;
  const index = cursor % items.length;
  return { idea: items[index], index, nextCursor: index + 1, poolSize: items.length };
}
