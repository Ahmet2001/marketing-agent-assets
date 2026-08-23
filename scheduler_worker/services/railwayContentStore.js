// Minimal S3-compatible client for reading/writing the scheduler's
// content_pool.txt (one small plain-text object). Deliberately not the full
// media-storage layer Kara Tahta uses internally (video/audio upload,
// signed URLs, legacy Supabase Storage) -- this worker only ever needs to
// read and occasionally overwrite one text file.
import { GetObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3';

const endpoint = process.env.MEDIA_S3_ENDPOINT;
const bucket = process.env.MEDIA_S3_BUCKET;
const region = process.env.MEDIA_S3_REGION || 'auto';
const accessKeyId = process.env.MEDIA_S3_ACCESS_KEY_ID;
const secretAccessKey = process.env.MEDIA_S3_SECRET_ACCESS_KEY;
const urlStyle = String(process.env.MEDIA_S3_URL_STYLE || 'virtual-host').toLowerCase();

export const railwayMediaConfigured = Boolean(endpoint && bucket && accessKeyId && secretAccessKey);

let client;
function requireClient() {
  if (!railwayMediaConfigured) {
    throw new Error('Bucket ayarlari eksik (MEDIA_S3_ENDPOINT/BUCKET/ACCESS_KEY_ID/SECRET_ACCESS_KEY).');
  }
  if (!client) {
    client = new S3Client({
      endpoint,
      region,
      forcePathStyle: urlStyle === 'path',
      credentials: { accessKeyId, secretAccessKey }
    });
  }
  return client;
}

function cleanObjectPath(value) {
  const clean = String(value || '')
    .replace(/^\/+/, '')
    .split('/')
    .filter((part) => part && part !== '.' && part !== '..')
    .join('/');
  if (!clean) throw new Error('Gecerli bir nesne yolu gerekli.');
  return clean;
}

function objectKeyFor(bucketPrefix, storagePath) {
  return `${cleanObjectPath(bucketPrefix)}/${cleanObjectPath(storagePath)}`;
}

export async function readRailwayObjectText({ bucket: bucketPrefix, storagePath }) {
  const s3 = requireClient();
  const response = await s3.send(new GetObjectCommand({ Bucket: bucket, Key: objectKeyFor(bucketPrefix, storagePath) }));
  const chunks = [];
  for await (const chunk of response.Body) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

export async function writeRailwayObjectText({ bucket: bucketPrefix, storagePath, text }) {
  const s3 = requireClient();
  const body = Buffer.from(String(text ?? ''), 'utf8');
  await s3.send(new PutObjectCommand({
    Bucket: bucket,
    Key: objectKeyFor(bucketPrefix, storagePath),
    Body: body,
    ContentLength: body.length,
    ContentType: 'text/plain; charset=utf-8'
  }));
}
