import { createClient } from '@supabase/supabase-js';

const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
const table = 'publish_jobs';

if (!url || !key) {
  throw new Error('Supabase queue requires SUPABASE_URL and SUPABASE_SECRET_KEY.');
}

const supabase = createClient(url, key, {
  auth: { persistSession: false, autoRefreshToken: false }
});

export async function claimNextJob() {
  const { data, error } = await supabase.rpc('claim_publish_job');
  if (error) throw error;
  return data || null;
}

export async function finishJob({ jobId, results }) {
  const { error } = await supabase
    .from(table)
    .update({ status: 'done', results, completed_at: new Date().toISOString(), updated_at: new Date().toISOString() })
    .eq('id', jobId);
  if (error) throw error;
}

export async function failJob({ jobId, results, error: message }) {
  const { error } = await supabase
    .from(table)
    .update({
      status: 'failed', results, error: String(message || 'Publishing failed.'),
      completed_at: new Date().toISOString(), updated_at: new Date().toISOString()
    })
    .eq('id', jobId);
  if (error) throw error;
}
