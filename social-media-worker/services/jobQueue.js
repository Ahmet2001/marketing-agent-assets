import { pathToFileURL } from 'node:url';
import path from 'node:path';

let adapterPromise;

async function loadAdapter() {
  if (adapterPromise) return adapterPromise;
  adapterPromise = (async () => {
    const moduleName = String(process.env.QUEUE_ADAPTER_MODULE || '').trim();
    if (!moduleName || moduleName === 'supabase') {
      return import('../adapters/supabase.js');
    }
    const moduleUrl = moduleName.startsWith('.') || moduleName.startsWith('/')
      ? pathToFileURL(path.resolve(process.cwd(), moduleName)).href
      : moduleName;
    return import(moduleUrl);
  })();
  return adapterPromise;
}

async function call(name, payload) {
  const adapter = await loadAdapter();
  if (typeof adapter[name] !== 'function') {
    throw new Error(`Queue adapter must export ${name}().`);
  }
  return adapter[name](payload);
}

export const claimNextJob = () => call('claimNextJob');
export const finishJob = (payload) => call('finishJob', payload);
export const failJob = (payload) => call('failJob', payload);
