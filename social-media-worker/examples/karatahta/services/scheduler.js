// Scheduled content pipeline: on its own interval, picks the next idea from
// the content pool (services/contentPool.js), generates cards/a lesson via
// this same API, then publishes it -- all as plain HTTP calls to the
// backend's own /api endpoints (auth'd via the shared X-Scheduler-Token,
// see services/requestAuth.js), same as any other client would. Runs inside
// workers/socialPublisher.js so publishing stays on one process.
import { pickNextContentPoolItem } from './contentPool.js';
import { getSchedulerJob, updateSchedulerJob } from './supabaseStore.js';

const BACKEND_URL = String(process.env.BACKEND_INTERNAL_URL || '').replace(/\/+$/, '');
const INTERNAL_TOKEN = process.env.SCHEDULER_INTERNAL_TOKEN || '';
const TICK_MS = Math.max(15000, Number(process.env.SCHEDULER_TICK_MS) || 60000);
const JOB_POLL_MS = 5000;
const JOB_TIMEOUT_MS = Math.max(60000, Number(process.env.SCHEDULER_JOB_TIMEOUT_MS) || 15 * 60 * 1000);
const COMBO_GAP_MS = Math.max(0, Number(process.env.SCHEDULER_COMBO_GAP_MS) || 10 * 60 * 1000);

const JOB_TYPES = ['cards_carousel', 'lesson_video', 'combo'];
const runningLock = new Set();

function log(message, meta = null) {
  console.log(`[scheduler] ${message}${meta ? ` ${JSON.stringify(meta)}` : ''}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function internalFetch(path, options = {}) {
  return fetch(`${BACKEND_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Scheduler-Token': INTERNAL_TOKEN,
      ...(options.headers || {})
    }
  });
}

async function* readNdjson(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    // eslint-disable-next-line no-await-in-loop
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line);
    }
  }
  if (buffer.trim()) yield JSON.parse(buffer);
}

async function runCardsCarousel(idea) {
  const genResponse = await internalFetch('/api/cards/generate', {
    method: 'POST',
    body: JSON.stringify({ prompt: idea })
  });
  if (!genResponse.ok) {
    throw new Error(`cards/generate basarisiz (${genResponse.status})`);
  }
  let sessionId = null;
  let cardCount = 0;
  for await (const event of readNdjson(genResponse)) {
    if (event.type === 'card') cardCount += 1;
    else if (event.type === 'session') sessionId = event.id;
    else if (event.type === 'error') throw new Error(event.message);
  }
  if (!sessionId) {
    throw new Error('Kart oturumu olusturulamadi (session id gelmedi).');
  }
  if (cardCount < 2) {
    throw new Error(`Carousel icin yetersiz kart uretildi (${cardCount}).`);
  }

  const publishResponse = await internalFetch(`/api/cards/sessions/${sessionId}/publish-instagram`, {
    method: 'POST',
    body: JSON.stringify({ caption: `Kara Tahta | ${idea}` })
  });
  const publishData = await publishResponse.json();
  if (!publishResponse.ok) {
    throw new Error(publishData?.error || `publish-instagram basarisiz (${publishResponse.status})`);
  }
  return { sessionId, cardCount, instagram: publishData };
}

// Was temporarily shortened (3 segments / 3.5 min) to dodge a final-concat
// OOM under the single trial-plan render-worker replica -- concatVideos()
// now uses the concat demuxer (buildConcatArgs) instead of a filter_complex
// graph that held every segment's decoder open at once, which was the
// actual source of the memory blowup. Restored to the normal topic-mode
// default now that the root cause is fixed.
const SCHEDULED_VIDEO_SEGMENT_COUNT = Math.max(1, Number(process.env.SCHEDULER_VIDEO_SEGMENT_COUNT) || 8);
const SCHEDULED_VIDEO_MINUTES = Math.max(1, Number(process.env.SCHEDULER_VIDEO_MINUTES) || 10);

async function runLessonVideo(idea) {
  const genResponse = await internalFetch('/api/generate-lesson', {
    method: 'POST',
    body: JSON.stringify({
      topic: idea,
      duration_touched: true,
      target_segment_count: SCHEDULED_VIDEO_SEGMENT_COUNT,
      target_video_minutes: SCHEDULED_VIDEO_MINUTES
    })
  });
  const genData = await genResponse.json();
  if (!genResponse.ok) {
    throw new Error(genData?.error || `generate-lesson basarisiz (${genResponse.status})`);
  }
  const jobId = genData.id;
  const lessonId = genData.lessonId;
  if (!jobId || !lessonId) {
    throw new Error('generate-lesson beklenen id/lessonId dondurmedi.');
  }

  const deadline = Date.now() + JOB_TIMEOUT_MS;
  let finalStatus = null;
  while (Date.now() < deadline) {
    // eslint-disable-next-line no-await-in-loop
    await sleep(JOB_POLL_MS);
    // eslint-disable-next-line no-await-in-loop
    const statusResponse = await internalFetch(`/api/jobs/${jobId}`);
    // eslint-disable-next-line no-await-in-loop
    const statusData = await statusResponse.json();
    if (!statusResponse.ok) {
      throw new Error(statusData?.error || `jobs/:id basarisiz (${statusResponse.status})`);
    }
    if (statusData.status === 'done') {
      finalStatus = statusData;
      break;
    }
    if (statusData.status === 'failed') {
      throw new Error(statusData.error || 'Ders video uretimi basarisiz oldu.');
    }
  }
  if (!finalStatus) {
    throw new Error('Ders videosu zaman asimina ugradi.');
  }

  const publishResponse = await internalFetch('/api/social-publish', {
    method: 'POST',
    body: JSON.stringify({
      lesson_id: lessonId,
      title: idea,
      caption: `Kara Tahta | ${idea}`,
      privacy_status: 'public'
    })
  });
  const publishData = await publishResponse.json();
  if (!publishResponse.ok) {
    throw new Error(publishData?.error || `social-publish basarisiz (${publishResponse.status})`);
  }
  return { lessonId, jobId, publishJobId: publishData.publishJobId };
}

// Same idea, two posts in sequence: full lesson video first (YouTube +
// Instagram Reel), then -- once it's had a few minutes to actually appear --
// a second Instagram post as a kart carousel of the same topic.
async function runCombo(idea) {
  const lesson = await runLessonVideo(idea);
  log('Combo: video adimi bitti, carousel icin bekleniyor', { idea, gapMs: COMBO_GAP_MS });
  await sleep(COMBO_GAP_MS);
  const cards = await runCardsCarousel(idea);
  return { lesson, cards };
}

const RUNNERS = { cards_carousel: runCardsCarousel, lesson_video: runLessonVideo, combo: runCombo };

async function runJob(jobType) {
  if (runningLock.has(jobType)) return;
  runningLock.add(jobType);
  try {
    const { idea, index, nextCursor, poolSize } = await pickNextContentPoolItem(jobType);
    log('Zamanlanmis is basliyor', { jobType, idea, index, poolSize });
    const result = await RUNNERS[jobType](idea);
    const job = await getSchedulerJob(jobType);
    const intervalMinutes = Math.max(1, Number(job?.interval_minutes) || 1440);
    await updateSchedulerJob(jobType, {
      last_run_at: new Date().toISOString(),
      last_status: 'success',
      last_error: null,
      last_result: { idea, ...result },
      content_pool_cursor: nextCursor,
      next_run_at: new Date(Date.now() + intervalMinutes * 60000).toISOString()
    });
    log('Zamanlanmis is tamamlandi', { jobType, idea });
  } catch (error) {
    const job = await getSchedulerJob(jobType).catch(() => null);
    const intervalMinutes = Math.max(1, Number(job?.interval_minutes) || 60);
    await updateSchedulerJob(jobType, {
      last_run_at: new Date().toISOString(),
      last_status: 'error',
      last_error: String(error.message || error).slice(0, 2000),
      next_run_at: new Date(Date.now() + intervalMinutes * 60000).toISOString()
    }).catch(() => {});
    log('Zamanlanmis is hata verdi', { jobType, error: error.message });
  } finally {
    runningLock.delete(jobType);
  }
}

export function startSchedulerLoop() {
  if (!BACKEND_URL || !INTERNAL_TOKEN) {
    log('BACKEND_INTERNAL_URL veya SCHEDULER_INTERNAL_TOKEN tanimli degil, scheduler loop baslamiyor.');
    return;
  }
  log('Scheduler loop basladi', { tickMs: TICK_MS });
  setInterval(() => {
    for (const jobType of JOB_TYPES) {
      getSchedulerJob(jobType)
        .then((job) => {
          if (!job || !job.enabled) return;
          const due = !job.next_run_at || new Date(job.next_run_at).getTime() <= Date.now();
          if (due) void runJob(jobType);
        })
        .catch((error) => log('scheduler_jobs okunamadi', { jobType, error: error.message }));
    }
  }, TICK_MS);
}
