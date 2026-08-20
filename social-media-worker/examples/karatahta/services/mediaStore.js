import {
  DeleteObjectsCommand,
  GetObjectCommand,
  GetBucketCorsCommand,
  HeadObjectCommand,
  ListObjectsV2Command,
  PutBucketCorsCommand,
  PutObjectCommand,
  S3Client
} from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import { createHmac, timingSafeEqual } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import {
  createStorageSignedUrl as createSupabaseStorageSignedUrl,
  deleteStorageByPrefix as deleteSupabaseStorageByPrefix,
  storagePathFor,
  uploadDataUrl as uploadSupabaseDataUrl,
  uploadLocalFile as uploadSupabaseLocalFile
} from './supabaseStore.js';

// Every lesson's media lives under this relative path within each of these
// buckets (see storagePathFor) -- deleting a lesson removes everything
// under the prefix in whichever backend is actually configured.
const LESSON_MEDIA_BUCKETS = ['videos', 'audio', 'attachments'];

const configuredProvider = String(process.env.MEDIA_STORAGE_PROVIDER || 'supabase')
  .trim()
  .toLowerCase();
const railwayEndpoint = process.env.MEDIA_S3_ENDPOINT;
const railwayBucket = process.env.MEDIA_S3_BUCKET;
const railwayRegion = process.env.MEDIA_S3_REGION || 'auto';
const railwayAccessKeyId = process.env.MEDIA_S3_ACCESS_KEY_ID;
const railwaySecretAccessKey = process.env.MEDIA_S3_SECRET_ACCESS_KEY;
const railwayUrlStyle = String(process.env.MEDIA_S3_URL_STYLE || 'virtual-host').toLowerCase();
const localMediaRoot = path.resolve(process.env.MEDIA_LOCAL_DIR || path.resolve(process.cwd(), 'media'));
const localPublicBaseUrl = String(process.env.MEDIA_PUBLIC_BASE_URL || '').trim().replace(/\/+$/, '');
const localSigningSecret = String(process.env.MEDIA_SIGNING_SECRET || '').trim();

export const railwayMediaConfigured = Boolean(
  railwayEndpoint
  && railwayBucket
  && railwayAccessKeyId
  && railwaySecretAccessKey
);
export const mediaStorageProvider = ['local', 'railway'].includes(configuredProvider)
  ? configuredProvider
  : 'supabase';
export const localMediaConfigured = Boolean(
  localMediaRoot
  && localPublicBaseUrl
  && localSigningSecret
);

let s3Client;

function requireRailwayMedia() {
  if (!railwayMediaConfigured) {
    throw new Error('Railway Bucket ayarlari eksik.');
  }
  if (!s3Client) {
    s3Client = new S3Client({
      endpoint: railwayEndpoint,
      region: railwayRegion,
      forcePathStyle: railwayUrlStyle === 'path',
      credentials: {
        accessKeyId: railwayAccessKeyId,
        secretAccessKey: railwaySecretAccessKey
      }
    });
  }
  return s3Client;
}

function dataUrlToBuffer(dataUrl) {
  const raw = String(dataUrl || '');
  const base64 = raw.includes(',') ? raw.slice(raw.indexOf(',') + 1) : raw;
  return Buffer.from(base64, 'base64');
}

function cleanObjectPath(value) {
  const clean = String(value || '')
    .replace(/^\/+/, '')
    .split('/')
    .filter((part) => part && part !== '.' && part !== '..')
    .join('/');
  if (!clean) {
    throw new Error('Gecerli bir medya nesne yolu gerekli.');
  }
  return clean;
}

function requireLocalMedia() {
  if (!localMediaConfigured) {
    throw new Error('Yerel medya depolama ayarlari eksik.');
  }
}

export function isRailwayStoragePath(storagePath) {
  return String(storagePath || '').startsWith('railway://');
}

export function isLocalStoragePath(storagePath) {
  return String(storagePath || '').startsWith('local://');
}

export function railwayObjectKeyFor(bucket, storagePath) {
  if (isRailwayStoragePath(storagePath)) {
    return cleanObjectPath(String(storagePath).slice('railway://'.length));
  }
  return `${cleanObjectPath(bucket)}/${cleanObjectPath(storagePath)}`;
}

export function railwayStoragePathFor(objectKey) {
  return `railway://${cleanObjectPath(objectKey)}`;
}

export function localObjectKeyFor(bucket, storagePath) {
  if (isLocalStoragePath(storagePath)) {
    return cleanObjectPath(String(storagePath).slice('local://'.length));
  }
  return `${cleanObjectPath(bucket)}/${cleanObjectPath(storagePath)}`;
}

export function localStoragePathFor(objectKey) {
  return `local://${cleanObjectPath(objectKey)}`;
}

function localFilePathForObjectKey(objectKey) {
  const cleanKey = cleanObjectPath(objectKey);
  const fullPath = path.resolve(localMediaRoot, cleanKey);
  if (fullPath !== localMediaRoot && !fullPath.startsWith(`${localMediaRoot}${path.sep}`)) {
    throw new Error('Gecersiz yerel medya dosya yolu.');
  }
  return fullPath;
}

export function createLocalMediaSignature(objectKey, expiresAtUnix, secret = localSigningSecret) {
  if (!secret) {
    throw new Error('MEDIA_SIGNING_SECRET gerekli.');
  }
  const cleanKey = cleanObjectPath(objectKey);
  return createHmac('sha256', secret)
    .update(`${cleanKey}\n${Number(expiresAtUnix)}`)
    .digest('hex');
}

export function verifyLocalMediaSignature({
  objectKey,
  expiresAtUnix,
  signature,
  secret = localSigningSecret,
  nowUnix = Math.floor(Date.now() / 1000)
}) {
  const expires = Number(expiresAtUnix);
  if (!Number.isInteger(expires) || expires < nowUnix || !/^[a-f0-9]{64}$/i.test(String(signature || ''))) {
    return false;
  }
  const expected = Buffer.from(createLocalMediaSignature(objectKey, expires, secret), 'hex');
  const received = Buffer.from(String(signature), 'hex');
  return expected.length === received.length && timingSafeEqual(expected, received);
}

export function resolveSignedLocalMediaRequest({
  objectKey,
  expiresAtUnix,
  signature,
  nowUnix
}) {
  requireLocalMedia();
  const cleanKey = cleanObjectPath(objectKey);
  if (!verifyLocalMediaSignature({
    objectKey: cleanKey,
    expiresAtUnix,
    signature,
    nowUnix
  })) {
    throw Object.assign(new Error('Gecersiz veya suresi dolmus medya baglantisi.'), {
      statusCode: 403
    });
  }
  return {
    objectKey: cleanKey,
    fullPath: localFilePathForObjectKey(cleanKey)
  };
}

export function normalizeSignedUrlTtlSeconds(value, fallback = 3600) {
  const parsed = Number(value);
  const seconds = Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
  return Math.min(86400, Math.max(60, seconds));
}

export async function uploadBufferToRailway({
  bucket,
  storagePath,
  buffer,
  contentType
}) {
  const client = requireRailwayMedia();
  const objectKey = railwayObjectKeyFor(bucket, storagePath);
  const body = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer);
  await client.send(new PutObjectCommand({
    Bucket: railwayBucket,
    Key: objectKey,
    Body: body,
    ContentLength: body.length,
    ContentType: contentType
  }));
  const head = await client.send(new HeadObjectCommand({
    Bucket: railwayBucket,
    Key: objectKey
  }));
  if (Number(head.ContentLength) !== body.length) {
    throw new Error(`Railway Bucket yukleme dogrulamasi basarisiz: ${objectKey}`);
  }
  return {
    bucket: railwayBucket,
    storagePath: railwayStoragePathFor(objectKey),
    publicUrl: null
  };
}

// Small plain-text objects (e.g. the scheduler's content_pool.txt) --
// deliberately separate from uploadBufferToRailway/createStorageSignedUrl
// since these are read/written directly server-side, never signed for a
// browser.
export async function readRailwayObjectText({ bucket, storagePath }) {
  const client = requireRailwayMedia();
  const objectKey = railwayObjectKeyFor(bucket, storagePath);
  const response = await client.send(new GetObjectCommand({ Bucket: railwayBucket, Key: objectKey }));
  const chunks = [];
  for await (const chunk of response.Body) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString('utf8');
}

export async function writeRailwayObjectText({ bucket, storagePath, text }) {
  const client = requireRailwayMedia();
  const objectKey = railwayObjectKeyFor(bucket, storagePath);
  const body = Buffer.from(String(text ?? ''), 'utf8');
  await client.send(new PutObjectCommand({
    Bucket: railwayBucket,
    Key: objectKey,
    Body: body,
    ContentLength: body.length,
    ContentType: 'text/plain; charset=utf-8'
  }));
}

async function uploadLocalFileToRailway({ bucket, localPath, storagePath, contentType }) {
  const client = requireRailwayMedia();
  const objectKey = railwayObjectKeyFor(bucket, storagePath);
  const stat = await fs.stat(localPath);
  await client.send(new PutObjectCommand({
    Bucket: railwayBucket,
    Key: objectKey,
    Body: createReadStream(localPath),
    ContentLength: stat.size,
    ContentType: contentType
  }));
  const head = await client.send(new HeadObjectCommand({
    Bucket: railwayBucket,
    Key: objectKey
  }));
  if (Number(head.ContentLength) !== stat.size) {
    throw new Error(`Railway Bucket yukleme dogrulamasi basarisiz: ${objectKey}`);
  }
  return {
    bucket: railwayBucket,
    storagePath: railwayStoragePathFor(objectKey),
    publicUrl: null
  };
}

async function writeBufferToLocal({ bucket, storagePath, buffer }) {
  requireLocalMedia();
  const objectKey = localObjectKeyFor(bucket, storagePath);
  const fullPath = localFilePathForObjectKey(objectKey);
  const body = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer);
  await fs.mkdir(path.dirname(fullPath), { recursive: true });
  const temporaryPath = `${fullPath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(temporaryPath, body, { mode: 0o640 });
  await fs.rename(temporaryPath, fullPath);
  const stat = await fs.stat(fullPath);
  if (stat.size !== body.length) {
    throw new Error(`Yerel medya yazma dogrulamasi basarisiz: ${objectKey}`);
  }
  return {
    bucket,
    storagePath: localStoragePathFor(objectKey),
    publicUrl: null
  };
}

async function uploadLocalFileToLocal({ bucket, localPath, storagePath }) {
  return writeBufferToLocal({
    bucket,
    storagePath,
    buffer: await fs.readFile(localPath)
  });
}

export async function uploadLocalFile(options) {
  if (mediaStorageProvider === 'local') {
    return uploadLocalFileToLocal(options);
  }
  if (mediaStorageProvider === 'railway') {
    return uploadLocalFileToRailway(options);
  }
  return uploadSupabaseLocalFile(options);
}

export async function uploadDataUrl(options) {
  if (mediaStorageProvider === 'local') {
    return writeBufferToLocal({
      bucket: options.bucket,
      storagePath: options.storagePath,
      buffer: dataUrlToBuffer(options.dataUrl)
    });
  }
  if (mediaStorageProvider === 'railway') {
    return uploadBufferToRailway({
      bucket: options.bucket,
      storagePath: options.storagePath,
      buffer: dataUrlToBuffer(options.dataUrl),
      contentType: options.contentType
    });
  }
  return uploadSupabaseDataUrl(options);
}

async function deleteLocalPrefix(bucket, prefix) {
  requireLocalMedia();
  const objectKey = localObjectKeyFor(bucket, prefix);
  const fullPath = localFilePathForObjectKey(objectKey);
  await fs.rm(fullPath, { recursive: true, force: true });
}

async function deleteRailwayPrefix(bucket, prefix) {
  const client = requireRailwayMedia();
  const objectPrefix = railwayObjectKeyFor(bucket, prefix);
  let continuationToken;
  do {
    const listResult = await client.send(new ListObjectsV2Command({
      Bucket: railwayBucket,
      Prefix: objectPrefix,
      ContinuationToken: continuationToken
    }));
    const objects = (listResult.Contents || [])
      .map((item) => ({ Key: item.Key }))
      .filter((item) => item.Key);
    if (objects.length) {
      await client.send(new DeleteObjectsCommand({
        Bucket: railwayBucket,
        Delete: { Objects: objects }
      }));
    }
    continuationToken = listResult.IsTruncated ? listResult.NextContinuationToken : undefined;
  } while (continuationToken);
}

// Best-effort: removes a lesson's rendered videos/audio/attachments from
// whichever media backend is configured. Failures here are per-bucket and
// collected rather than thrown, so a partial storage cleanup never blocks
// deleting the lesson's database row (the row is the source of truth for
// what the user sees; leftover orphan files are a disk-usage concern, not
// a correctness one).
export async function deleteLessonStorage({ userId, lessonId }) {
  const prefix = `${cleanObjectPath(`users/${userId}`)}/lessons/${cleanObjectPath(lessonId)}`;
  const errors = [];
  for (const bucket of LESSON_MEDIA_BUCKETS) {
    try {
      if (mediaStorageProvider === 'local') {
        await deleteLocalPrefix(bucket, prefix);
      } else if (mediaStorageProvider === 'railway') {
        await deleteRailwayPrefix(bucket, prefix);
      } else {
        await deleteSupabaseStorageByPrefix(bucket, prefix);
      }
    } catch (error) {
      errors.push(`${bucket}: ${error.message}`);
    }
  }
  return { errors };
}

export async function createStorageSignedUrl({
  bucket,
  storagePath,
  expiresInSeconds = 3600
}) {
  if (isLocalStoragePath(storagePath)) {
    requireLocalMedia();
    const ttlSeconds = normalizeSignedUrlTtlSeconds(expiresInSeconds);
    const objectKey = localObjectKeyFor(bucket, storagePath);
    const expiresAtUnix = Math.floor(Date.now() / 1000) + ttlSeconds;
    const signature = createLocalMediaSignature(objectKey, expiresAtUnix);
    const encodedPath = objectKey
      .split('/')
      .map((part) => encodeURIComponent(part))
      .join('/');
    return {
      signedUrl: `${localPublicBaseUrl}/media/${encodedPath}?expires=${expiresAtUnix}&signature=${signature}`,
      expiresInSeconds: ttlSeconds,
      expiresAt: new Date(expiresAtUnix * 1000).toISOString()
    };
  }
  if (!isRailwayStoragePath(storagePath)) {
    return createSupabaseStorageSignedUrl({ bucket, storagePath, expiresInSeconds });
  }
  const client = requireRailwayMedia();
  const ttlSeconds = normalizeSignedUrlTtlSeconds(expiresInSeconds);
  const signedUrl = await getSignedUrl(
    client,
    new GetObjectCommand({
      Bucket: railwayBucket,
      Key: railwayObjectKeyFor(bucket, storagePath)
    }),
    { expiresIn: ttlSeconds }
  );
  return {
    signedUrl,
    expiresInSeconds: ttlSeconds,
    expiresAt: new Date(Date.now() + ttlSeconds * 1000).toISOString()
  };
}

export async function configureRailwayBucketCors(allowedOrigins) {
  const client = requireRailwayMedia();
  const origins = [...new Set((allowedOrigins || []).map((origin) => String(origin).trim()).filter(Boolean))];
  if (!origins.length) {
    throw new Error('Railway Bucket CORS icin en az bir origin gerekli.');
  }
  await client.send(new PutBucketCorsCommand({
    Bucket: railwayBucket,
    CORSConfiguration: {
      CORSRules: [{
        AllowedOrigins: origins,
        AllowedMethods: ['GET', 'HEAD', 'PUT'],
        AllowedHeaders: ['*'],
        ExposeHeaders: ['ETag', 'Content-Length', 'Content-Range', 'Accept-Ranges'],
        MaxAgeSeconds: 3600
      }]
    }
  }));
  const current = await client.send(new GetBucketCorsCommand({
    Bucket: railwayBucket
  }));
  return current.CORSRules || [];
}

export { storagePathFor };
