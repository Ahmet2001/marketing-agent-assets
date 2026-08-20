import { supabase, supabaseConfigured } from './supabaseStore.js';

function requireQueue() {
  if (!supabaseConfigured || !supabase) {
    throw new Error('Sosyal medya kuyrugu icin Supabase ayarlari eksik.');
  }
  return supabase;
}

export async function createSocialPublishJob({ lessonId, videoId, userId, targetPlatform, caption, title, description, privacyStatus }) {
  const client = requireQueue();
  const { data, error } = await client
    .from('social_publish_jobs')
    .insert({
      lesson_id: lessonId,
      video_id: videoId,
      user_id: userId,
      target_platform: targetPlatform,
      caption: caption || null,
      title: title || null,
      description: description || null,
      privacy_status: privacyStatus || 'private'
    })
    .select('*')
    .single();
  if (error) throw error;
  return data;
}

export async function getSocialPublishJobForUser({ jobId, userId }) {
  const client = requireQueue();
  const { data, error } = await client
    .from('social_publish_jobs')
    .select('*')
    .eq('id', jobId)
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function claimNextSocialPublishJob() {
  const client = requireQueue();
  const { data: queued, error: readError } = await client
    .from('social_publish_jobs')
    .select('*')
    .eq('status', 'queued')
    .order('created_at', { ascending: true })
    .limit(1)
    .maybeSingle();
  if (readError) throw readError;
  if (!queued) return null;

  const { data: claimed, error: claimError } = await client
    .from('social_publish_jobs')
    .update({
      status: 'processing',
      attempts: Number(queued.attempts || 0) + 1,
      started_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      error: null
    })
    .eq('id', queued.id)
    .eq('status', 'queued')
    .select('*')
    .maybeSingle();
  if (claimError) throw claimError;
  return claimed || null;
}

export async function finishSocialPublishJob({ jobId, instagramResult, youtubeResult, tiktokResult }) {
  const client = requireQueue();
  const { error } = await client
    .from('social_publish_jobs')
    .update({
      status: 'done',
      instagram_result: instagramResult,
      youtube_result: youtubeResult,
      tiktok_result: tiktokResult,
      completed_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    })
    .eq('id', jobId);
  if (error) throw error;
}

export async function failSocialPublishJob({ jobId, instagramResult, youtubeResult, tiktokResult, error }) {
  const client = requireQueue();
  const { error: updateError } = await client
    .from('social_publish_jobs')
    .update({
      status: 'failed',
      instagram_result: instagramResult,
      youtube_result: youtubeResult,
      tiktok_result: tiktokResult,
      error: String(error || 'Sosyal medya yayinlama basarisiz.'),
      completed_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    })
    .eq('id', jobId);
  if (updateError) throw updateError;
}
