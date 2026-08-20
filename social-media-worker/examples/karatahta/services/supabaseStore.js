import { createClient } from '@supabase/supabase-js';
import { promises as fs } from 'node:fs';
import path from 'node:path';

const supabaseUrl = process.env.SUPABASE_URL;
const publishableKey = process.env.SUPABASE_PUBLISHABLE_KEY || process.env.SUPABASE_ANON_KEY;
const secretKey = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
const devUserId = process.env.DEV_USER_ID;
const storagePublic = String(process.env.SUPABASE_STORAGE_PUBLIC || 'false').toLowerCase() === 'true';
const requestedProfileCacheTtlMs = Number(process.env.AUTH_PROFILE_CACHE_TTL_MS || 300000);
const profileCacheTtlMs = Number.isFinite(requestedProfileCacheTtlMs)
  ? Math.max(30000, requestedProfileCacheTtlMs)
  : 300000;

export const supabaseConfigured = Boolean(supabaseUrl && secretKey);
export const supabaseAuthConfigured = Boolean(supabaseUrl && publishableKey);

export const supabase = supabaseConfigured
  ? createClient(supabaseUrl, secretKey, {
      auth: {
        persistSession: false,
        autoRefreshToken: false
      }
    })
  : null;

const supabaseAuth = supabaseAuthConfigured
  ? createClient(supabaseUrl, publishableKey, {
      auth: {
        persistSession: false,
        autoRefreshToken: false
      }
    })
  : null;

let devProfileReady = false;
const profileCache = new Map();

function requireSupabase() {
  if (!supabaseConfigured || !supabase) {
    throw new Error('Supabase ayarlari eksik.');
  }
  return supabase;
}

async function ensureDevProfile() {
  if (!devUserId) {
    throw new Error('AUTH_REQUIRED=false icin DEV_USER_ID gerekli.');
  }
  if (devProfileReady) {
    return;
  }
  const client = requireSupabase();
  const { error } = await client
    .from('profiles')
    .upsert({
      id: devUserId,
      display_name: 'Dev User'
    }, {
      onConflict: 'id'
    });
  if (error) throw error;
  devProfileReady = true;
}

function displayNameFromAuthUser(user, fallbackEmail) {
  return user?.user_metadata?.display_name
    || user?.user_metadata?.name
    || fallbackEmail?.split('@')[0]
    || user?.email?.split('@')[0]
    || 'Kara Tahta Kullanıcısı';
}

function cacheProfile(authUserId, profile) {
  if (!authUserId || !profile) return profile;
  profileCache.set(authUserId, {
    profile,
    expiresAt: Date.now() + profileCacheTtlMs
  });
  return profile;
}

function cachedProfile(authUserId) {
  const cached = profileCache.get(authUserId);
  if (!cached) return null;
  if (cached.expiresAt <= Date.now()) {
    profileCache.delete(authUserId);
    return null;
  }
  return cached.profile;
}

export function authUserFromClaims(claims) {
  if (!claims?.sub) return null;
  return {
    id: claims.sub,
    email: claims.email || null,
    user_metadata: claims.user_metadata || claims.raw_user_meta_data || {}
  };
}

export async function upsertProfileFromAuthUser(user) {
  if (!user?.id) {
    throw new Error('Gecerli Supabase auth kullanicisi bulunamadi.');
  }

  const client = requireSupabase();
  const email = user.email || null;
  const fullPayload = {
    auth_user_id: user.id,
    email,
    display_name: displayNameFromAuthUser(user, email),
    avatar_url: user.user_metadata?.avatar_url || null,
    last_seen_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  };
  let { data, error } = await client
    .from('profiles')
    .upsert(fullPayload, {
      onConflict: 'auth_user_id'
    })
    .select('*')
    .single();
  if (error && /column .* does not exist/i.test(error.message || '')) {
    const fallback = await client
      .from('profiles')
      .upsert({
        auth_user_id: user.id,
        display_name: fullPayload.display_name
      }, {
        onConflict: 'auth_user_id'
      })
      .select('*')
      .single();
    data = fallback.data;
    error = fallback.error;
  }
  if (error) throw error;
  return cacheProfile(user.id, data);
}

export async function getProfileForAccessToken(accessToken) {
  if (!supabaseAuth) {
    throw new Error('Supabase auth ayarlari eksik.');
  }
  const { data, error } = await supabaseAuth.auth.getClaims(accessToken);
  const authUser = authUserFromClaims(data?.claims);
  if (error || !authUser) {
    const authError = new Error('Oturum gecersiz veya suresi dolmus.');
    authError.statusCode = 401;
    throw authError;
  }

  const cached = cachedProfile(authUser.id);
  if (cached) {
    return cached;
  }

  const client = requireSupabase();
  const profileResult = await client
    .from('profiles')
    .select('*')
    .eq('auth_user_id', authUser.id)
    .maybeSingle();
  if (profileResult.error) throw profileResult.error;
  if (profileResult.data) {
    return cacheProfile(authUser.id, profileResult.data);
  }

  return upsertProfileFromAuthUser(authUser);
}

export async function signUpWithPassword({ email, password, displayName, emailRedirectTo }) {
  if (!supabaseAuth) {
    throw new Error('Supabase auth ayarlari eksik.');
  }
  const { data, error } = await supabaseAuth.auth.signUp({
    email,
    password,
    options: {
      data: {
        display_name: displayName || email.split('@')[0]
      },
      ...(emailRedirectTo ? { emailRedirectTo } : {})
    }
  });
  if (error) throw error;
  const profile = data.user ? await upsertProfileFromAuthUser(data.user) : null;
  return { session: data.session, user: data.user, profile };
}

export async function signInWithPassword({ email, password }) {
  if (!supabaseAuth) {
    throw new Error('Supabase auth ayarlari eksik.');
  }
  const { data, error } = await supabaseAuth.auth.signInWithPassword({ email, password });
  if (error) throw error;
  const profile = data.user ? await upsertProfileFromAuthUser(data.user) : null;
  return { session: data.session, user: data.user, profile };
}

export async function createOAuthSignInUrl({
  provider = 'google',
  redirectTo,
  scopes,
  queryParams,
  authClient = supabaseAuth
}) {
  if (!authClient) {
    throw new Error('Supabase auth ayarlari eksik.');
  }
  if (provider !== 'google') {
    const providerError = new Error('Desteklenmeyen OAuth saglayicisi.');
    providerError.statusCode = 400;
    throw providerError;
  }
  const { data, error } = await authClient.auth.signInWithOAuth({
    provider,
    options: {
      skipBrowserRedirect: true,
      ...(redirectTo ? { redirectTo } : {}),
      ...(scopes ? { scopes } : {}),
      ...(queryParams ? { queryParams } : {})
    }
  });
  if (error) throw error;
  if (!data?.url) {
    const oauthError = new Error('Google giris adresi olusturulamadi.');
    oauthError.statusCode = 502;
    throw oauthError;
  }
  return data.url;
}

export async function saveOAuthRefreshToken({ userId, provider, refreshToken, scope = null }) {
  if (!userId || !provider || !refreshToken) {
    throw new Error('userId, provider ve refreshToken gerekli.');
  }
  const client = requireSupabase();
  const { error } = await client
    .from('oauth_connections')
    .upsert({
      user_id: userId,
      provider,
      refresh_token: refreshToken,
      scope,
      updated_at: new Date().toISOString()
    }, { onConflict: 'user_id,provider' });
  if (error) throw error;
}

export async function getOAuthConnection({ userId, provider }) {
  if (!userId || !provider) return null;
  const client = requireSupabase();
  const { data, error } = await client
    .from('oauth_connections')
    .select('refresh_token, drive_folder_id')
    .eq('user_id', userId)
    .eq('provider', provider)
    .maybeSingle();
  if (error) throw error;
  if (!data) return null;
  return { refreshToken: data.refresh_token, driveFolderId: data.drive_folder_id || null };
}

export async function saveOAuthDriveFolderId({ userId, provider, driveFolderId }) {
  if (!userId || !provider || !driveFolderId) {
    throw new Error('userId, provider ve driveFolderId gerekli.');
  }
  const client = requireSupabase();
  const { error } = await client
    .from('oauth_connections')
    .update({ drive_folder_id: driveFolderId, updated_at: new Date().toISOString() })
    .eq('user_id', userId)
    .eq('provider', provider);
  if (error) throw error;
}

export async function refreshAuthSession(refreshToken) {
  if (!supabaseAuth) {
    throw new Error('Supabase auth ayarlari eksik.');
  }
  const { data, error } = await supabaseAuth.auth.refreshSession({ refresh_token: refreshToken });
  if (error) throw error;
  const profile = data.user ? await upsertProfileFromAuthUser(data.user) : null;
  return { session: data.session, user: data.user, profile };
}

export async function requestPasswordReset({ email, redirectTo }) {
  if (!supabaseAuth) {
    throw new Error('Supabase auth ayarlari eksik.');
  }
  const { error } = await supabaseAuth.auth.resetPasswordForEmail(email, {
    ...(redirectTo ? { redirectTo } : {})
  });
  if (error) throw error;
}

export async function updatePasswordWithAccessToken({ accessToken, password }) {
  if (!supabaseUrl || !publishableKey) {
    throw new Error('Supabase auth ayarlari eksik.');
  }
  const userClient = createClient(supabaseUrl, publishableKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false
    },
    global: {
      headers: {
        Authorization: `Bearer ${accessToken}`
      }
    }
  });
  const { data, error } = await userClient.auth.updateUser({ password });
  if (error) throw error;
  return { user: data.user };
}

function dataUrlToBuffer(dataUrl) {
  const raw = String(dataUrl || '');
  const base64 = raw.includes(',') ? raw.slice(raw.indexOf(',') + 1) : raw;
  return Buffer.from(base64, 'base64');
}

function safePathPart(value) {
  return String(value || 'item').replace(/[^\w.-]/g, '_').slice(0, 80) || 'item';
}

function extensionFromMime(mimeType) {
  if (mimeType === 'image/png') return '.png';
  if (mimeType === 'image/webp') return '.webp';
  if (mimeType === 'audio/mpeg') return '.mp3';
  if (mimeType === 'video/mp4') return '.mp4';
  return mimeType?.startsWith('image/') ? '.jpg' : '';
}

async function insertRow(table, payload) {
  const client = requireSupabase();
  const { data, error } = await client.from(table).insert(payload).select('*').single();
  if (error) throw error;
  return data;
}

async function updateRows(table, match, payload) {
  const client = requireSupabase();
  let query = client.from(table).update(payload);
  Object.entries(match).forEach(([key, value]) => {
    query = query.eq(key, value);
  });
  const { data, error } = await query.select('*');
  if (error) throw error;
  return data;
}

async function uploadBuffer(bucket, storagePath, buffer, contentType) {
  const client = requireSupabase();
  const { error } = await client.storage
    .from(bucket)
    .upload(storagePath, buffer, {
      contentType,
      upsert: true
    });
  if (error) throw error;

  let publicUrl = null;
  if (storagePublic) {
    const { data } = client.storage.from(bucket).getPublicUrl(storagePath);
    publicUrl = data?.publicUrl || null;
  }

  return { bucket, storagePath, publicUrl };
}

export function userId() {
  return devUserId;
}

export async function createLesson({ userId = devUserId, title, topic, studentLevel, targetMinutes, targetSegmentCount, orientation, sourceType }) {
  if (userId === devUserId) {
    await ensureDevProfile();
  }
  return insertRow('lessons', {
    user_id: userId,
    title: title || topic || 'Yeni ders',
    topic: topic || title || null,
    student_level: studentLevel || null,
    // The legacy schema stores this display field as integer minutes. The
    // persisted lesson plan retains the precise duration (e.g. 1.5 minutes).
    target_minutes: Number.isFinite(Number(targetMinutes)) ? Math.ceil(Number(targetMinutes)) : null,
    target_segment_count: targetSegmentCount || null,
    orientation: orientation === 'vertical' ? 'vertical' : 'horizontal',
    status: 'planned',
    source_type: sourceType || 'topic'
  });
}

export async function updateLesson(lessonId, patch) {
  if (!lessonId) return null;
  const rows = await updateRows('lessons', { id: lessonId }, {
    ...patch,
    updated_at: new Date().toISOString()
  });
  return rows?.[0] || null;
}

export async function getLessonForUser({ lessonId, userId }) {
  if (!lessonId || !userId) return null;
  const client = requireSupabase();
  const { data, error } = await client
    .from('lessons')
    .select('*')
    .eq('id', lessonId)
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function deleteLesson({ lessonId, userId }) {
  if (!lessonId || !userId) return false;
  const client = requireSupabase();
  const { error, count } = await client
    .from('lessons')
    .delete({ count: 'exact' })
    .eq('id', lessonId)
    .eq('user_id', userId);
  if (error) throw error;
  return Boolean(count);
}

export async function listLessonsForUser({ userId, limit = 30 }) {
  if (!userId) return [];
  const client = requireSupabase();
  const { data, error } = await client
    .from('lessons')
    .select(`
      id,
      title,
      topic,
      status,
      source_type,
      created_at,
      updated_at,
      lesson_videos (
        id,
        local_video_path,
        video_storage_path,
        duration_seconds,
        created_at
      )
    `)
    .eq('user_id', userId)
    .not('source_type', 'in', '("youtube_import","catalog_curated")')
    .order('updated_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data || []).map((lesson) => ({
    ...lesson,
    latest_video: [...(lesson.lesson_videos || [])]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0] || null,
    lesson_videos: undefined
  }));
}

function mapCatalogLesson(lesson) {
  const doneVideo = [...(lesson.lesson_videos || [])]
    .filter((video) => video.status === 'done' && video.video_storage_path)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0] || null;
  return {
    id: lesson.id,
    title: lesson.title,
    topic: lesson.topic,
    is_public: lesson.is_public,
    created_at: lesson.created_at,
    updated_at: lesson.updated_at,
    video: doneVideo
  };
}

export async function listPublicCatalogLessons({ limit = 60 } = {}) {
  const client = requireSupabase();
  const { data, error } = await client
    .from('lessons')
    .select(`
      id,
      title,
      topic,
      is_public,
      created_at,
      updated_at,
      lesson_videos (
        id,
        status,
        video_storage_path,
        poster_storage_path,
        duration_seconds,
        created_at
      )
    `)
    .eq('is_public', true)
    .order('updated_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data || [])
    .map(mapCatalogLesson)
    .filter((lesson) => lesson.video);
}

export async function listCatalogLessonsForUser({ userId, limit = 60 }) {
  if (!userId) return [];
  const client = requireSupabase();
  const { data, error } = await client
    .from('lessons')
    .select(`
      id,
      title,
      topic,
      is_public,
      created_at,
      updated_at,
      lesson_videos (
        id,
        status,
        video_storage_path,
        poster_storage_path,
        duration_seconds,
        created_at
      )
    `)
    .eq('user_id', userId)
    .order('updated_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data || [])
    .map(mapCatalogLesson)
    .filter((lesson) => lesson.video);
}

export async function getPublicLessonVideo({ lessonId }) {
  if (!lessonId) return null;
  const client = requireSupabase();
  const [lessonResult, videoResult] = await Promise.all([
    client
      .from('lessons')
      .select('id,title,topic,is_public')
      .eq('id', lessonId)
      .eq('is_public', true)
      .maybeSingle(),
    client
      .from('lesson_videos')
      .select('*')
      .eq('lesson_id', lessonId)
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle()
  ]);
  if (lessonResult.error) throw lessonResult.error;
  if (videoResult.error) throw videoResult.error;
  if (!lessonResult.data) return null;
  return {
    lesson: lessonResult.data,
    video: videoResult.data || null
  };
}

export async function getLessonDetailForUser({ lessonId, userId, messageLimit = 50 }) {
  if (!lessonId || !userId) return null;
  const client = requireSupabase();
  const [
    lessonResult,
    planResult,
    segmentsResult,
    videoResult,
    chatResult
  ] = await Promise.all([
    client
      .from('lessons')
      .select('*')
      .eq('id', lessonId)
      .eq('user_id', userId)
      .maybeSingle(),
    client
      .from('lesson_plans')
      .select('*')
      .eq('lesson_id', lessonId)
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle(),
    client
      .from('lesson_segments')
      .select('*')
      .eq('lesson_id', lessonId)
      .order('order_index', { ascending: true }),
    client
      .from('lesson_videos')
      .select('*')
      .eq('lesson_id', lessonId)
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle(),
    client
      .from('chats')
      .select('id')
      .eq('lesson_id', lessonId)
      .eq('user_id', userId)
      .maybeSingle()
  ]);

  for (const result of [lessonResult, planResult, segmentsResult, videoResult, chatResult]) {
    if (result.error) throw result.error;
  }
  if (!lessonResult.data) return null;

  let messages = [];
  if (chatResult.data?.id) {
    const messagesResult = await client
      .from('chat_messages')
      .select('*')
      .eq('chat_id', chatResult.data.id)
      .order('created_at', { ascending: false })
      .limit(Math.max(1, Math.min(100, Number(messageLimit) || 50)));
    if (messagesResult.error) throw messagesResult.error;
    messages = [...(messagesResult.data || [])].reverse();
  }

  return {
    lesson: lessonResult.data,
    plan: planResult.data?.plan_json || null,
    segments: segmentsResult.data || [],
    video: videoResult.data || null,
    chat: chatResult.data || null,
    messages
  };
}

export async function getLessonVideoForUser({ lessonId, userId }) {
  if (!lessonId || !userId) return null;
  const client = requireSupabase();
  const [lessonResult, videoResult] = await Promise.all([
    client
      .from('lessons')
      .select('id,title,topic')
      .eq('id', lessonId)
      .eq('user_id', userId)
      .maybeSingle(),
    client
      .from('lesson_videos')
      .select('*')
      .eq('lesson_id', lessonId)
      .order('created_at', { ascending: false })
      .limit(1)
      .maybeSingle()
  ]);
  if (lessonResult.error) throw lessonResult.error;
  if (videoResult.error) throw videoResult.error;
  if (!lessonResult.data) return null;
  return {
    lesson: lessonResult.data,
    video: videoResult.data || null
  };
}

export async function getLessonVideoByIdForUser({ videoId, userId }) {
  if (!videoId || !userId) return null;
  const client = requireSupabase();
  const videoResult = await client
    .from('lesson_videos')
    .select('*')
    .eq('id', videoId)
    .maybeSingle();
  if (videoResult.error) throw videoResult.error;
  if (!videoResult.data) return null;

  const lessonResult = await client
    .from('lessons')
    .select('id,title,topic')
    .eq('id', videoResult.data.lesson_id)
    .eq('user_id', userId)
    .maybeSingle();
  if (lessonResult.error) throw lessonResult.error;
  if (!lessonResult.data) return null;

  return { lesson: lessonResult.data, video: videoResult.data };
}

export async function savePlan({ lessonId, provider, model, prompt, plan, rawResponse }) {
  return insertRow('lesson_plans', {
    lesson_id: lessonId,
    provider,
    model,
    prompt: prompt || null,
    plan_json: plan,
    raw_response: rawResponse || null
  });
}

export async function saveSegments({ lessonId, segments, startIndex = 0 }) {
  const client = requireSupabase();
  const rows = (segments || []).map((segment, index) => ({
    lesson_id: lessonId,
    segment_key: segment.id || `s${index + 1}`,
    title: segment.title || null,
    duration_seconds: segment.duration_seconds || null,
    learning_objective: segment.learning_objective || null,
    narration: segment.narration || null,
    animation_json: segment.animation || null,
    order_index: startIndex + index,
    status: 'planned'
  }));
  if (!rows.length) return [];
  const { data, error } = await client
    .from('lesson_segments')
    .upsert(rows, { onConflict: 'lesson_id,segment_key' })
    .select('*');
  if (error) throw error;
  return data || [];
}

export async function getSegment({ lessonId, segmentKey }) {
  if (!lessonId || !segmentKey) return null;
  const client = requireSupabase();
  const { data, error } = await client
    .from('lesson_segments')
    .select('*')
    .eq('lesson_id', lessonId)
    .eq('segment_key', segmentKey)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function updateSegment(segmentId, patch) {
  if (!segmentId) return null;
  const rows = await updateRows('lesson_segments', { id: segmentId }, {
    ...patch,
    updated_at: new Date().toISOString()
  });
  return rows?.[0] || null;
}

export async function saveSpeechScript({ segmentId, provider, model, speech }) {
  return insertRow('speech_scripts', {
    segment_id: segmentId,
    provider,
    model,
    speech_json: speech,
    speech_text: speech?.speech_text || null,
    cue_plan: speech?.cue_plan || null,
    duration_seconds: speech?.estimated_seconds || null
  });
}

export async function saveManimCode({ segmentId, provider, model, code, attempt = 1, isRepair = false, repairReason = null, renderError = null }) {
  return insertRow('manim_codes', {
    segment_id: segmentId || null,
    provider,
    model,
    code,
    attempt,
    is_repair: isRepair,
    repair_reason: repairReason,
    render_error: renderError
  });
}

export async function uploadLocalFile({ bucket, localPath, storagePath, contentType }) {
  const buffer = await fs.readFile(localPath);
  return uploadBuffer(bucket, storagePath, buffer, contentType);
}

export async function uploadDataUrl({ bucket, dataUrl, storagePath, contentType }) {
  return uploadBuffer(bucket, storagePath, dataUrlToBuffer(dataUrl), contentType);
}

export function normalizeSignedUrlTtlSeconds(value, fallback = 3600) {
  const parsed = Number(value);
  const seconds = Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
  return Math.min(86400, Math.max(60, seconds));
}

export async function createStorageSignedUrl({
  bucket,
  storagePath,
  expiresInSeconds = 3600
}) {
  if (!bucket || !storagePath) {
    throw new Error('Signed URL icin bucket ve storage path gerekli.');
  }
  const client = requireSupabase();
  const ttlSeconds = normalizeSignedUrlTtlSeconds(expiresInSeconds);
  const { data, error } = await client.storage
    .from(bucket)
    .createSignedUrl(storagePath, ttlSeconds);
  if (error) throw error;
  if (!data?.signedUrl) {
    throw new Error('Supabase signed video URL dondurmedi.');
  }
  return {
    signedUrl: data.signedUrl,
    expiresInSeconds: ttlSeconds,
    expiresAt: new Date(Date.now() + ttlSeconds * 1000).toISOString()
  };
}

async function listSupabaseStorageFilesRecursive(bucket, prefix) {
  const client = requireSupabase();
  const { data, error } = await client.storage.from(bucket).list(prefix, { limit: 1000 });
  if (error) throw error;
  const files = [];
  for (const entry of data || []) {
    const entryPath = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.id === null) {
      files.push(...await listSupabaseStorageFilesRecursive(bucket, entryPath));
    } else {
      files.push(entryPath);
    }
  }
  return files;
}

export async function deleteStorageByPrefix(bucket, prefix) {
  const client = requireSupabase();
  const files = await listSupabaseStorageFilesRecursive(bucket, prefix);
  if (!files.length) return 0;
  const { error } = await client.storage.from(bucket).remove(files);
  if (error) throw error;
  return files.length;
}

export function storagePathFor({ userId = devUserId, lessonId, segmentKey, kind, fileName }) {
  const parts = ['users', userId, 'lessons', lessonId];
  if (segmentKey) {
    parts.push('segments', safePathPart(segmentKey));
  }
  parts.push(kind, safePathPart(fileName));
  return parts.join('/');
}

export async function saveTtsOutput({ segmentId, provider = 'google_cloud', voiceName, speakingRate, durationSeconds, storagePath, publicUrl }) {
  return insertRow('tts_outputs', {
    segment_id: segmentId,
    provider,
    voice_name: voiceName || null,
    speaking_rate: speakingRate || null,
    duration_seconds: durationSeconds || null,
    storage_path: storagePath || null,
    public_url: publicUrl || null
  });
}

export async function saveVideoRender({ segmentId, manimCodeId, quality, videoStoragePath, localVideoPath, audioStoragePath, backgroundMusicPath, durationSeconds, stdout, stderr }) {
  return insertRow('video_renders', {
    segment_id: segmentId || null,
    manim_code_id: manimCodeId || null,
    quality,
    status: 'done',
    video_storage_path: videoStoragePath || null,
    local_video_path: localVideoPath || null,
    audio_storage_path: audioStoragePath || null,
    background_music_path: backgroundMusicPath || null,
    duration_seconds: durationSeconds || null,
    stdout: stdout || null,
    stderr: stderr || null
  });
}

export async function saveLessonVideo({ lessonId, videoStoragePath, localVideoPath, durationSeconds, segmentRenderIds, posterStoragePath }) {
  return insertRow('lesson_videos', {
    lesson_id: lessonId,
    status: 'done',
    video_storage_path: videoStoragePath || null,
    local_video_path: localVideoPath || null,
    duration_seconds: durationSeconds || null,
    segment_render_ids: segmentRenderIds || [],
    poster_storage_path: posterStoragePath || null
  });
}

export async function createGenerationJob({ appJobId, lessonId, total, current, message }) {
  return insertRow('generation_jobs', {
    app_job_id: appJobId,
    lesson_id: lessonId || null,
    status: 'queued',
    progress: 0,
    total: total || 0,
    current: current || null,
    message: message || null
  });
}

export async function updateGenerationJob(appJobId, patch) {
  const rows = await updateRows('generation_jobs', { app_job_id: appJobId }, {
    status: patch.status,
    progress: patch.progress,
    total: patch.total,
    current: patch.current,
    message: patch.message,
    error: patch.error,
    completed_at: patch.completedAt || null,
    updated_at: new Date().toISOString()
  });
  return rows?.[0] || null;
}

export async function getGenerationJobForUser({ appJobId, userId }) {
  if (!appJobId || !userId) return null;
  const client = requireSupabase();
  const { data, error } = await client
    .from('generation_jobs')
    .select('*, lessons!inner(id,user_id)')
    .eq('app_job_id', appJobId)
    .eq('lessons.user_id', userId)
    .maybeSingle();
  if (error) throw error;
  if (!data) return null;
  const { lessons, ...job } = data;
  return job;
}

export async function appendGenerationEvent({ jobId, lessonId, segmentId, level = 'info', message, payload }) {
  return insertRow('generation_events', {
    job_id: jobId || null,
    lesson_id: lessonId || null,
    segment_id: segmentId || null,
    level,
    message,
    payload: payload || null
  });
}

export async function createRenderWorkerJob({ generationJobId, lessonId, segmentId, segmentIndex, input }) {
  return insertRow('render_worker_jobs', {
    generation_job_id: generationJobId,
    lesson_id: lessonId,
    segment_id: segmentId || null,
    segment_index: segmentIndex,
    input: input || {}
  });
}

export async function updateRenderWorkerJob({ id, status, workerId, attempt, queueJobId, output, error, completedAt }) {
  const payload = { updated_at: new Date().toISOString() };
  if (status !== undefined) payload.status = status;
  if (workerId !== undefined) payload.worker_id = workerId || null;
  if (Number.isFinite(attempt)) payload.attempt = attempt;
  if (queueJobId !== undefined) payload.queue_job_id = queueJobId || null;
  if (output !== undefined) payload.output = output || null;
  if (error !== undefined) payload.error = error || null;
  if (status === 'running') payload.started_at = new Date().toISOString();
  if (completedAt !== undefined) payload.completed_at = completedAt;
  else if (['done', 'failed'].includes(status)) payload.completed_at = new Date().toISOString();
  const rows = await updateRows('render_worker_jobs', { id }, payload);
  return rows?.[0] || null;
}

export async function getRenderWorkerJob(id) {
  const client = requireSupabase();
  const { data, error } = await client
    .from('render_worker_jobs')
    .select('*')
    .eq('id', id)
    .maybeSingle();
  if (error) throw error;
  return data || null;
}

export async function getRenderWorkerInput({ lessonId, segmentId }) {
  const client = requireSupabase();
  const { data: segment, error: segmentError } = await client
    .from('lesson_segments')
    .select('id, lesson_id, segment_key, lessons!inner(user_id)')
    .eq('lesson_id', lessonId)
    .eq('segment_key', segmentId)
    .maybeSingle();
  if (segmentError) throw segmentError;
  if (!segment) return null;
  const { data: code, error: codeError } = await client
    .from('manim_codes')
    .select('*')
    .eq('segment_id', segment.id)
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle();
  if (codeError) throw codeError;
  const { data: tts, error: ttsError } = await client
    .from('tts_outputs')
    .select('*')
    .eq('segment_id', segment.id)
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle();
  if (ttsError) throw ttsError;
  return {
    segment: { ...segment, user_id: segment.lessons?.user_id || null },
    code,
    tts
  };
}

export async function getOrCreateChat({ userId = devUserId, lessonId, source }) {
  if (userId === devUserId) {
    await ensureDevProfile();
  }
  const client = requireSupabase();
  const { data: existing, error: selectError } = await client
    .from('chats')
    .select('*')
    .eq('lesson_id', lessonId)
    .eq('user_id', userId)
    .maybeSingle();
  if (selectError) throw selectError;
  if (existing) {
    // Bir ders Katalog'dan "Open in chat" ile acildiysa, o sohbeti daha once
    // Karatahta akisinda olusmus olsa bile Katalog gecmisine "yukselt" --
    // tersi olmaz (source alani yalnizca migration uygulandiysa referans
    // edilir, o yuzden normal Karatahta akisi bu parametre hic gecilmeden
    // migration'sIz calismaya devam eder).
    if (source === 'catalog' && existing.source !== 'catalog') {
      const rows = await updateRows('chats', { id: existing.id }, { source: 'catalog' });
      return rows?.[0] || existing;
    }
    return existing;
  }
  return insertRow('chats', {
    lesson_id: lessonId,
    user_id: userId,
    ...(source ? { source } : {})
  });
}

export async function saveChatMessage({ chatId, role, content, timestampSeconds, timestampLabel, frameAttachmentId, provider, model, context }) {
  return insertRow('chat_messages', {
    chat_id: chatId,
    role,
    content,
    timestamp_seconds: timestampSeconds ?? null,
    timestamp_label: timestampLabel || null,
    frame_attachment_id: frameAttachmentId || null,
    provider: provider || null,
    model: model || null,
    context_json: context || null
  });
}

export async function saveAttachment({ userId = devUserId, lessonId, chatMessageId = null, type, mimeType, storagePath, metadata }) {
  if (userId === devUserId) {
    await ensureDevProfile();
  }
  return insertRow('attachments', {
    lesson_id: lessonId || null,
    chat_message_id: chatMessageId,
    user_id: userId,
    type,
    mime_type: mimeType || null,
    storage_path: storagePath || null,
    metadata: metadata || null
  });
}

export function fileNameFromLocalPath(localPath, fallbackName) {
  return safePathPart(path.basename(localPath || fallbackName || 'file'));
}

export function extensionFromContentType(mimeType) {
  return extensionFromMime(mimeType);
}

export async function createCardSession({ userId = devUserId, title, cards }) {
  if (userId === devUserId) {
    await ensureDevProfile();
  }
  return insertRow('card_sessions', {
    user_id: userId,
    title: String(title || 'Kart oturumu').slice(0, 240),
    cards: cards || [],
    messages: []
  });
}

export async function appendCardSessionMessages({ sessionId, userId, messages }) {
  if (!sessionId || !userId || !messages?.length) return null;
  const client = requireSupabase();
  const { data: existing, error: selectError } = await client
    .from('card_sessions')
    .select('messages')
    .eq('id', sessionId)
    .eq('user_id', userId)
    .maybeSingle();
  if (selectError) throw selectError;
  if (!existing) return null;
  const nextMessages = [...(existing.messages || []), ...messages];
  const rows = await updateRows('card_sessions', { id: sessionId, user_id: userId }, {
    messages: nextMessages,
    updated_at: new Date().toISOString()
  });
  return rows?.[0] || null;
}

export async function listCardSessionsForUser({ userId, limit = 60 }) {
  if (!userId) return [];
  const client = requireSupabase();
  const { data, error } = await client
    .from('card_sessions')
    .select('id, title, created_at, updated_at, cards')
    .eq('user_id', userId)
    .order('updated_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return data || [];
}

export async function getCardSessionForUser({ sessionId, userId }) {
  if (!sessionId || !userId) return null;
  const client = requireSupabase();
  const { data, error } = await client
    .from('card_sessions')
    .select('*')
    .eq('id', sessionId)
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function getPublicCardSession({ sessionId }) {
  if (!sessionId) return null;
  const client = requireSupabase();
  const { data, error } = await client
    .from('card_sessions')
    .select('*')
    .eq('id', sessionId)
    .eq('is_public', true)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function listPublicCardSessions({ limit = 60 } = {}) {
  const client = requireSupabase();
  const { data, error } = await client
    .from('card_sessions')
    .select('id, title, created_at, updated_at, cards')
    .eq('is_public', true)
    .order('updated_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return data || [];
}

export async function listCardSessionsForUserWithVisibility({ userId, limit = 60 }) {
  if (!userId) return [];
  const client = requireSupabase();
  const { data, error } = await client
    .from('card_sessions')
    .select('id, title, created_at, updated_at, cards, is_public')
    .eq('user_id', userId)
    .order('updated_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return data || [];
}

export async function setCardSessionPublic({ sessionId, userId, isPublic }) {
  if (!sessionId || !userId) return null;
  const rows = await updateRows('card_sessions', { id: sessionId, user_id: userId }, {
    is_public: Boolean(isPublic),
    updated_at: new Date().toISOString()
  });
  return rows?.[0] || null;
}

export async function getSchedulerJob(jobType) {
  const client = requireSupabase();
  const { data, error } = await client
    .from('scheduler_jobs')
    .select('*')
    .eq('job_type', jobType)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function listSchedulerJobs() {
  const client = requireSupabase();
  const { data, error } = await client
    .from('scheduler_jobs')
    .select('*')
    .order('job_type');
  if (error) throw error;
  return data || [];
}

export async function updateSchedulerJob(jobType, patch) {
  const rows = await updateRows('scheduler_jobs', { job_type: jobType }, {
    ...patch,
    updated_at: new Date().toISOString()
  });
  return rows[0] || null;
}

export async function listChatsForUser({ userId, limit = 60 }) {
  if (!userId) return [];
  const client = requireSupabase();
  const { data, error } = await client
    .from('chats')
    .select(`
      id,
      lesson_id,
      created_at,
      lessons (
        id,
        title,
        topic,
        lesson_videos ( poster_storage_path, created_at )
      )
    `)
    .eq('user_id', userId)
    .eq('source', 'catalog')
    .order('created_at', { ascending: false })
    .limit(limit);
  if (error) throw error;
  return (data || [])
    .filter((chat) => chat.lessons)
    .map((chat) => {
      const latestVideo = [...(chat.lessons.lesson_videos || [])]
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0] || null;
      return {
        lessonId: chat.lesson_id,
        title: chat.lessons.title,
        topic: chat.lessons.topic,
        createdAt: chat.created_at,
        posterStoragePath: latestVideo?.poster_storage_path || null
      };
    });
}
