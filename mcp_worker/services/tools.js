import { z } from 'zod';
import {
  startLessonPlanFromQuestion,
  startFullVideoFromPlan,
  startLessonFromTopic,
  getJobStatus,
  generateCards
} from './karatahtaClient.js';

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function textResult(payload) {
  return { content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] };
}

const lessonWaitMs = Math.max(5000, Number(process.env.MCP_LESSON_WAIT_MS) || 240000);
const cardsWaitMs = Math.max(5000, Number(process.env.MCP_CARDS_WAIT_MS) || 120000);
const JOB_POLL_MS = 5000;

// Blocks (polling /api/jobs/:id) up to lessonWaitMs so a caller normally
// gets the finished video in one call. If generation is still running when
// the wait budget runs out, returns early with status:"running" instead of
// hanging indefinitely -- the job itself keeps going server-side, and the
// returned jobId lets the caller resume with check_lesson_status.
export function registerGenerateLessonVideo(server) {
  server.registerTool('generate_lesson_video', {
    title: 'Generate lesson video',
    description: 'Creates a full narrated + animated lesson video for a topic, or a step-by-step solution video for a specific question. Waits for the render to finish (up to a few minutes) and returns the video URL; if it takes longer, returns a jobId to check later with check_lesson_status.',
    inputSchema: {
      topic: z.string().min(1).optional().describe('General subject to teach, e.g. "Pisagor teoremi". Omit if using `question`.'),
      question: z.string().min(1).optional().describe('A specific question to solve step by step, e.g. "2x + 3 = 11 denklemini coz". Omit if using `topic`.'),
      student_level: z.enum(['beginner', 'intermediate', 'advanced']).optional(),
      target_video_minutes: z.number().min(0.5).max(20).optional().describe('Only used with `topic`; ignored for `question` (question videos are auto-sized, max 3 min).'),
      target_segment_count: z.number().int().min(1).max(12).optional().describe('Only used with `topic`.')
    }
  }, async ({ topic, question, student_level: studentLevel, target_video_minutes: targetVideoMinutes, target_segment_count: targetSegmentCount }) => {
    if (!topic && !question) {
      return textResult({ status: 'failed', error: 'topic veya question alanlarindan biri gerekli.' });
    }

    let started;
    try {
      if (question) {
        const planned = await startLessonPlanFromQuestion({ note: question, studentLevel });
        started = await startFullVideoFromPlan({ plan: planned.plan, lessonId: planned.lessonId });
      } else {
        started = await startLessonFromTopic({ topic, targetVideoMinutes, targetSegmentCount, studentLevel });
      }
    } catch (error) {
      return textResult({ status: 'failed', error: error.message });
    }

    const jobId = started.id;
    const lessonId = started.lessonId;
    const deadline = Date.now() + lessonWaitMs;

    while (Date.now() < deadline) {
      // eslint-disable-next-line no-await-in-loop
      await sleep(JOB_POLL_MS);
      let status;
      try {
        // eslint-disable-next-line no-await-in-loop
        status = await getJobStatus(jobId);
      } catch (error) {
        return textResult({ status: 'failed', jobId, lessonId, error: error.message });
      }
      if (status.status === 'done') {
        return textResult({
          status: 'done',
          jobId,
          lessonId,
          videoUrl: status.result?.videoUrl || null
        });
      }
      if (status.status === 'failed') {
        return textResult({ status: 'failed', jobId, lessonId, error: status.error || 'Video uretimi basarisiz oldu.' });
      }
    }

    return textResult({
      status: 'running',
      jobId,
      lessonId,
      message: 'Video hala render ediliyor. check_lesson_status ile jobId kullanarak takip et.'
    });
  });
}

export function registerCheckLessonStatus(server) {
  server.registerTool('check_lesson_status', {
    title: 'Check lesson video status',
    description: 'Checks the current status/progress of a lesson video job started by generate_lesson_video, using the jobId it returned.',
    inputSchema: {
      job_id: z.string().min(1)
    }
  }, async ({ job_id: jobId }) => {
    try {
      const status = await getJobStatus(jobId);
      return textResult({
        status: status.status,
        progress: status.progress,
        total: status.total,
        message: status.message,
        error: status.error,
        videoUrl: status.result?.videoUrl || null
      });
    } catch (error) {
      return textResult({ status: 'failed', error: error.message });
    }
  });
}

export function registerGenerateCards(server) {
  server.registerTool('generate_cards', {
    title: 'Generate teaching cards',
    description: `Creates a short sequence (1-4) of teaching card images with explanations, for a general topic or a specific question. Not job-based -- no jobId/status tool to resume with. Waits up to ~${Math.round(cardsWaitMs / 1000)}s; if the backend's model is slow, returns whatever cards finished in time with status:"partial" rather than blocking indefinitely.`,
    inputSchema: {
      topic: z.string().min(1).optional().describe('General subject, e.g. "Vektor toplama". Omit if using `question`.'),
      question: z.string().min(1).optional().describe('A specific question to solve card by card. Omit if using `topic`.'),
      include_images: z.boolean().optional().describe('Include each card\'s base64 PNG data URL in the response. Defaults to false to keep the response small -- titles/explanations are usually enough.')
    }
  }, async ({ topic, question, include_images: includeImages }) => {
    if (!topic && !question) {
      return textResult({ status: 'failed', error: 'topic veya question alanlarindan biri gerekli.' });
    }
    try {
      const { sessionId, cards, timedOut } = await generateCards({ topic, question, deadlineMs: Date.now() + cardsWaitMs });
      const formatted = cards.map((card) => ({
        index: card.index,
        title: card.title,
        explanation: card.explanation,
        ...(includeImages ? { imageDataUrl: card.imageDataUrl } : {})
      }));
      return textResult(
        timedOut
          ? { status: 'partial', sessionId, cards: formatted, message: `Zaman asimina ugradi, ${formatted.length} kart tamamlanmis haliyle donduruldu.` }
          : { status: 'done', sessionId, cards: formatted }
      );
    } catch (error) {
      return textResult({ status: 'failed', error: error.message });
    }
  });
}

export function registerAllTools(server) {
  registerGenerateLessonVideo(server);
  registerCheckLessonStatus(server);
  registerGenerateCards(server);
}
