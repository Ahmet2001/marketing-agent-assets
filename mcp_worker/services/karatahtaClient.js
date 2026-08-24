// Thin HTTP client for the target backend -- same shared-secret pattern as
// scheduler_worker's internalFetch (X-Scheduler-Token resolves server-side
// to a fixed user identity, see the backend's services/requestAuth.js).
const BACKEND_URL = String(process.env.BACKEND_INTERNAL_URL || '').replace(/\/+$/, '');
const TOKEN = process.env.MCP_BACKEND_TOKEN || '';

export function backendConfigured() {
  return Boolean(BACKEND_URL && TOKEN);
}

async function call(path, options = {}) {
  if (!backendConfigured()) {
    throw new Error('BACKEND_INTERNAL_URL / MCP_BACKEND_TOKEN tanimli degil.');
  }
  const response = await fetch(`${BACKEND_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Scheduler-Token': TOKEN,
      ...(options.headers || {})
    }
  });
  return response;
}

async function callJson(path, options = {}) {
  const response = await call(path, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(data?.error || `${path} basarisiz (${response.status}).`);
  }
  return data;
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

export async function startLessonPlanFromQuestion({ note, image, studentLevel }) {
  return callJson('/api/question-plan', {
    method: 'POST',
    body: JSON.stringify({ note, image, student_level: studentLevel })
  });
}

export async function startFullVideoFromPlan({ plan, lessonId }) {
  return callJson('/api/full-video', {
    method: 'POST',
    body: JSON.stringify({ plan, lesson_id: lessonId })
  });
}

export async function startLessonFromTopic({ topic, targetVideoMinutes, targetSegmentCount, studentLevel }) {
  return callJson('/api/generate-lesson', {
    method: 'POST',
    body: JSON.stringify({
      topic,
      duration_touched: Boolean(targetVideoMinutes || targetSegmentCount),
      target_video_minutes: targetVideoMinutes,
      target_segment_count: targetSegmentCount,
      student_level: studentLevel
    })
  });
}

export async function getJobStatus(jobId) {
  return callJson(`/api/jobs/${encodeURIComponent(jobId)}`);
}

// deadlineMs (Date.now()-based, optional): if the backend's model is slow,
// stop reading the stream once it's passed rather than waiting indefinitely
// -- returns whatever cards arrived in time, with timedOut:true so the
// caller can report a partial result instead of hanging.
export async function generateCards({ topic, question, deadlineMs = null }) {
  const response = await call('/api/cards/generate', {
    method: 'POST',
    body: JSON.stringify({ topic, question })
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.error || `/api/cards/generate basarisiz (${response.status}).`);
  }
  const cards = [];
  let sessionId = null;
  let timedOut = false;
  for await (const event of readNdjson(response)) {
    if (event.type === 'card') cards.push(event.card);
    else if (event.type === 'session') sessionId = event.id;
    else if (event.type === 'error') throw new Error(event.message);
    if (deadlineMs && Date.now() >= deadlineMs) {
      timedOut = true;
      break;
    }
  }
  return { sessionId, cards, timedOut };
}
