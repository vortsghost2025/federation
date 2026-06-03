import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';

const dbPath = path.resolve('genesis.db');
if (fs.existsSync(dbPath)) fs.unlinkSync(dbPath);

const serverPath = path.resolve('src/index.ts');
const env = { ...process.env, GENESIS_MEMORY_DB: dbPath };

const proc = spawn('npx', ['tsx', serverPath], {
  cwd: path.resolve('.'),
  env,
  stdio: ['pipe', 'pipe', 'pipe'],
  shell: true,
});

let outBuf = '';
let errBuf = '';
const pending = new Map();
let nextId = 1;

proc.stdout.on('data', (d) => {
  outBuf += d.toString();
  while (true) {
    const idx = outBuf.indexOf('\n');
    if (idx === -1) break;
    const line = outBuf.slice(0, idx).trim();
    outBuf = outBuf.slice(idx + 1);
    if (!line) continue;
    try {
      const obj = JSON.parse(line);
      if (obj.id != null && pending.has(String(obj.id))) {
        const { resolve } = pending.get(String(obj.id));
        pending.delete(String(obj.id));
        resolve(obj);
      }
    } catch {}
  }
});

proc.stderr.on('data', (d) => {
  const s = d.toString();
  errBuf += s;
  process.stderr.write('[SERVER STDERR] ' + s);
});

function send(method, params) {
  const id = nextId++;
  const msg = JSON.stringify({ jsonrpc: '2.0', method, id, params });
  const promise = new Promise((resolve) => {
    pending.set(String(id), { resolve });
  });
  proc.stdin.write(msg + '\n', 'utf8');
  return { id, response: promise };
}

function sendNotif(method, params) {
  const msg = JSON.stringify({ jsonrpc: '2.0', method, params });
  proc.stdin.write(msg + '\n', 'utf8');
}

function callTool(name, args) {
  return send('tools/call', { name, arguments: args });
}

async function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

async function withTimeout(promise, label, ms = 5000) {
  let timer;
  const race = Promise.race([
    promise,
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`TIMEOUT after ${ms}ms waiting for: ${label}`)), ms);
    }),
  ]);
  try {
    const result = await race;
    clearTimeout(timer);
    return result;
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
}

async function run() {
  console.log('=== genesis-memory smoke test ===\n');

  const results = {};

  const steps = [
    { label: 'initialize', fn: () => send('initialize', {
      protocolVersion: '2024-11-05',
      capabilities: {},
      clientInfo: { name: 'smoke-test', version: '1.0.0' },
    })},
    { label: 'initialized notif', fn: () => { sendNotif('initialized', {}); return null; }, noWait: true },
    { label: 'tools/list', fn: () => send('tools/list', {}) },
    { label: 'addMemory #1', fn: () => callTool('addMemory', {
      content: 'Phase 1 deployed - genesis memory server online',
      containerTag: 'genesis-kernel',
      metadata: { phase: 1, status: 'deployed' },
    })},
    { label: 'addMemory #2', fn: () => callTool('addMemory', {
      content: 'Infrastructure config for Docker and Nginx',
      containerTag: 'infra',
      metadata: { type: 'config' },
    })},
    { label: 'addMemory #3', fn: () => callTool('addMemory', {
      content: 'Refactoring plan for consciousness simulation',
      containerTag: 'genesis-refactor',
      metadata: { priority: 'high' },
    })},
    { label: 'searchMemories (kernel)', fn: () => callTool('searchMemories', {
      query: 'Phase 1 deployed',
      containerTag: 'genesis-kernel',
    })},
    { label: 'searchMemories (infra)', fn: () => callTool('searchMemories', {
      query: 'Docker Nginx',
      containerTag: 'infra',
    })},
    { label: 'listMemories (all)', fn: () => callTool('listMemories', { limit: 20 }) },
    { label: 'listMemories (infra)', fn: () => callTool('listMemories', { containerTag: 'infra' }) },
    { label: 'getStats (all)', fn: () => callTool('getStats', {}) },
    { label: 'getStats (tag)', fn: () => callTool('getStats', { containerTag: 'genesis-kernel' }) },
    { label: 'exportMemories', fn: () => callTool('exportMemories', {}) },
    { label: 'getMemory (not found)', fn: () => callTool('getMemory', { id: '00000000-0000-0000-0000-000000000000' }) },
    { label: 'updateMemory (not found)', fn: () => callTool('updateMemory', {
      id: '00000000-0000-0000-0000-000000000000',
      content: 'should fail',
    })},
    { label: 'deleteMemoriesByTag', fn: () => callTool('deleteMemoriesByTag', { containerTag: 'genesis-refactor' }) },
    { label: 'getStats (after delete)', fn: () => callTool('getStats', {}) },
  ];

  for (const step of steps) {
    console.log(`  sending: ${step.label}...`);
    try {
      const { id, response } = step.fn() || {};
      if (step.noWait || !response) {
        await wait(300);
        console.log(`  ok (notification): ${step.label}`);
        continue;
      }
      const result = await withTimeout(response, step.label, 5000);
      results[step.label] = result;
      console.log(`  ok: ${step.label}`);
      await wait(100);
    } catch (e) {
      console.log(`  FAIL: ${step.label} — ${e.message}`);
      console.log(`  stderr so far: ${errBuf.slice(-300)}`);
      proc.kill();
      process.exit(1);
    }
  }

  proc.stdin.end();

  const tests = [
    { name: 'initialize', expect: (r) => r.result?.protocolVersion === '2024-11-05' },
    { name: 'tools/list', expect: (r) => Array.isArray(r.result?.tools) && r.result.tools.length === 9 },
    { name: 'addMemory #1', expect: (r) => r.result?.content?.[0]?.text?.includes('"ok"') },
    { name: 'addMemory #2', expect: (r) => r.result?.content?.[0]?.text?.includes('"ok"') },
    { name: 'addMemory #3', expect: (r) => r.result?.content?.[0]?.text?.includes('"ok"') },
    { name: 'searchMemories (kernel)', expect: (r) => r.result?.content?.[0]?.text?.includes('Phase 1') },
    { name: 'searchMemories (infra)', expect: (r) => r.result?.content?.[0]?.text?.includes('Docker') },
    { name: 'listMemories (all)', expect: (r) => r.result?.content?.[0]?.text?.includes('genesis-kernel') },
    { name: 'listMemories (infra)', expect: (r) => r.result?.content?.[0]?.text?.includes('Docker') },
    { name: 'getStats (all)', expect: (r) => r.result?.content?.[0]?.text?.includes('"total"') },
    { name: 'getStats (tag)', expect: (r) => r.result?.content?.[0]?.text?.includes('"total"') },
    { name: 'exportMemories', expect: (r) => r.result?.content?.[0]?.text?.includes('memories') },
    { name: 'getMemory (not found)', expect: (r) => r.result?.content?.[0]?.text?.includes('not found') || r.result?.content?.[0]?.text?.includes('ok":false') },
    { name: 'updateMemory (not found)', expect: (r) => r.result?.content?.[0]?.text?.includes('not found') || r.result?.content?.[0]?.text?.includes('ok":false') },
    { name: 'deleteMemoriesByTag', expect: (r) => r.result?.content?.[0]?.text?.includes('"ok"') },
    { name: 'getStats (after delete)', expect: (r) => {
      const text = r.result?.content?.[0]?.text || '';
      try { const parsed = JSON.parse(text); return parsed.stats?.total === 2; } catch { return false; }
    }},
  ];

  let pass = 0;
  let fail = 0;
  for (const t of tests) {
    const r = results[t.name];
    const ok = r && t.expect(r);
    if (ok) {
      console.log(` PASS ${t.name}`);
      pass++;
    } else {
      console.log(` FAIL ${t.name}`);
      console.log(`  Response: ${JSON.stringify(r?.result || r?.error || 'no response').slice(0, 200)}`);
      fail++;
    }
  }

  console.log(`\n=== ${pass}/${pass + fail} passed, ${fail} failed ===`);

  if (errBuf.trim()) {
    console.log(`\nStderr:\n${errBuf.slice(0, 500)}`);
  }

  process.exit(fail > 0 ? 1 : 0);
}

run().catch(e => { console.error(e); process.exit(1); });
