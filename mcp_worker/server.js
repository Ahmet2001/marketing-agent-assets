import 'dotenv/config';

import express from 'express';
import { timingSafeEqual } from 'node:crypto';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { registerAllTools } from './services/tools.js';
import { backendConfigured } from './services/karatahtaClient.js';

const PORT = Number(process.env.PORT) || 8090;
const ACCESS_TOKEN = String(process.env.MCP_SERVER_ACCESS_TOKEN || '').trim();

function log(message, meta = null) {
  console.log(`[mcp-worker] ${message}${meta ? ` ${JSON.stringify(meta)}` : ''}`);
}

function requireAccessToken(req, res, next) {
  if (!ACCESS_TOKEN) {
    // Fails closed: an unset token means the server refuses everything
    // rather than silently running open on a public port.
    res.status(500).json({ error: 'MCP_SERVER_ACCESS_TOKEN tanimli degil.' });
    return;
  }
  const header = String(req.headers.authorization || '');
  const provided = header.match(/^Bearer\s+(.+)$/i)?.[1] || '';
  const providedBuffer = Buffer.from(provided);
  const expectedBuffer = Buffer.from(ACCESS_TOKEN);
  const matches = providedBuffer.length === expectedBuffer.length
    && timingSafeEqual(providedBuffer, expectedBuffer);
  if (!matches) {
    res.status(401).json({ error: 'Gecersiz veya eksik Authorization: Bearer <token>.' });
    return;
  }
  next();
}

function buildServer() {
  const server = new McpServer({ name: 'karatahta-mcp-worker', version: '0.1.0' });
  registerAllTools(server);
  return server;
}

const app = express();
app.use(express.json());

app.get('/health', (req, res) => {
  res.json({ ok: true, backendConfigured: backendConfigured() });
});

// Stateless mode (sessionIdGenerator: undefined): a fresh McpServer +
// transport per request. Simpler and safe for a worker with no client-side
// session state to preserve between calls; each tool call is independent
// anyway (generate_lesson_video's jobId is the only cross-call state, and
// that already lives in the backend, not in this process).
app.post('/mcp', requireAccessToken, async (req, res) => {
  try {
    const server = buildServer();
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on('close', () => {
      transport.close();
      server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (error) {
    log('MCP istegi islenemedi', { error: error.message });
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: '2.0',
        error: { code: -32603, message: 'Internal server error' },
        id: null
      });
    }
  }
});

app.get('/mcp', requireAccessToken, (req, res) => {
  res.status(405).json({
    jsonrpc: '2.0',
    error: { code: -32000, message: 'Method not allowed. Stateless server -- POST only.' },
    id: null
  });
});

app.listen(PORT, () => {
  if (!backendConfigured()) {
    log('UYARI: BACKEND_INTERNAL_URL / MCP_BACKEND_TOKEN eksik, tool cagrilari basarisiz olur.');
  }
  if (!ACCESS_TOKEN) {
    log('UYARI: MCP_SERVER_ACCESS_TOKEN tanimli degil, sunucu tum istekleri reddedecek.');
  }
  log(`MCP HTTP server ${PORT} portunda dinliyor`, { endpoint: '/mcp' });
});
