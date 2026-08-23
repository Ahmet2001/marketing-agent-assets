// Minimal Supabase access for the scheduler_jobs table -- deliberately not
// Kara Tahta's full supabaseStore.js (auth, lessons, chats, card sessions,
// etc). This worker only ever reads/updates its own scheduling state.
import { createClient } from '@supabase/supabase-js';

const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;

if (!url || !key) {
  throw new Error('Scheduler requires SUPABASE_URL and SUPABASE_SECRET_KEY.');
}

const supabase = createClient(url, key, {
  auth: { persistSession: false, autoRefreshToken: false }
});

export async function getSchedulerJob(jobType) {
  const { data, error } = await supabase
    .from('scheduler_jobs')
    .select('*')
    .eq('job_type', jobType)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function listSchedulerJobs() {
  const { data, error } = await supabase
    .from('scheduler_jobs')
    .select('*')
    .order('job_type');
  if (error) throw error;
  return data || [];
}

export async function updateSchedulerJob(jobType, patch) {
  const { data, error } = await supabase
    .from('scheduler_jobs')
    .update({ ...patch, updated_at: new Date().toISOString() })
    .eq('job_type', jobType)
    .select('*');
  if (error) throw error;
  return data?.[0] || null;
}
