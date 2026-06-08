/**
 * deploy.js — Deploy files from Gastown rig to Federation VPS via SSH (ssh2)
 * 
 * Usage:
 * node deploy.js <local-file> <remote-path> Deploy a single file
 * node deploy.js --target backend Deploy all backend Python files (recursive)
 * node deploy.js --target worker Deploy worker + rebuild Docker image
 * node deploy.js --target frontend Deploy all frontend HTML files
 * node deploy.js --target html Deploy a single HTML file (needs --file flag)
 * node deploy.js --target html --file simulation.html Deploy simulation.html only
 * 
 * Environment:
 * VPS_HOST - VPS IP (default: 187.77.3.56)
 * VPS_USER - SSH user (default: root)
 * VPS_KEY_PATH - Path to SSH private key (default: ~/.ssh/id_ed25519)
 * FEDERATION_DIR - Project root on rig (default: current directory)
 * VPS_BASE_DIR - Project root on VPS (default: /docker/federation-game)
 */
import { Client } from 'ssh2';
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { join, basename, resolve, relative } from 'node:path';
import { homedir } from 'node:os';
import { execFileSync } from 'node:child_process';

const VPS_HOST = process.env.VPS_HOST || '187.77.3.56';
const VPS_USER = process.env.VPS_USER || 'root';
const VPS_KEY_PATH = process.env.VPS_KEY_PATH || join(homedir(), '.ssh', 'id_ed25519');
// Walk up from cwd to find the project root (dir containing federation-game/)
function findProjectRoot(startDir) {
  let dir = startDir;
  for (let i = 0; i < 5; i++) {
    if (existsSync(join(dir, 'federation-game'))) return dir;
    const parent = join(dir, '..');
    if (parent === dir) break;
    dir = resolve(parent);
  }
  return startDir; // fallback to cwd
}

const FEDERATION_DIR = process.env.FEDERATION_DIR || findProjectRoot(process.cwd());
const VPS_BASE_DIR = process.env.VPS_BASE_DIR || '/docker/federation-game';

// Parse args
const args = process.argv.slice(2);
let target = null;
let localFile = null;
let remotePath = null;
let htmlFile = null;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--target') target = args[++i];
  else if (args[i] === '--file') htmlFile = args[++i];
  else if (!localFile) localFile = args[i];
  else if (!remotePath) remotePath = args[i];
}

// Recursively collect .py files from a directory (skips __pycache__)
function collectPyFiles(dir, baseDir = dir) {
  let results = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === '__pycache__') continue;
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      results = results.concat(collectPyFiles(fullPath, baseDir));
    } else if (entry.name.endsWith('.py')) {
      results.push({ local: fullPath, rel: relative(baseDir, fullPath) });
    }
  }
  return results;
}

// Determine files to deploy
let deployList = []; // [{local, remote, restart, mkdir}]

if (target === 'backend') {
  const backendDir = join(FEDERATION_DIR, 'federation-game', 'backend');
  if (!existsSync(backendDir)) {
    console.error(`❌ Backend dir not found: ${backendDir}`);
    process.exit(1);
  }
  const pyFiles = collectPyFiles(backendDir);
  for (const f of pyFiles) {
    const subDir = f.rel.includes('/') ? f.rel.substring(0, f.rel.lastIndexOf('/')) : '';
    deployList.push({
      local: f.local,
      remote: `${VPS_BASE_DIR}/backend/${f.rel.replace(/\\/g, '/')}`,
      restart: 'backend',
      mkdir: subDir ? `${VPS_BASE_DIR}/backend/${subDir.replace(/\\/g, '/')}` : null,
    });
  }
  console.log(`📦 Deploying ${pyFiles.length} backend files (${new Set(pyFiles.map(f => f.rel.split(/[/\\]/)[0] || '.')).size} dirs)...`);
// Also include smoke test script in backend deploys
const smokeTestLocal = join(FEDERATION_DIR, 'federation-game', 'backend', 'vps_test.py');
if (existsSync(smokeTestLocal)) {
  deployList.push({
    local: smokeTestLocal,
    remote: `${VPS_BASE_DIR}/backend/smoke_test.py`,
    restart: 'backend',
    mkdir: null,
  });
}

} else if (target === 'worker') {
  const workerFile = join(FEDERATION_DIR, 'federation-game', 'backend', 'worker.py');
  if (!existsSync(workerFile)) {
    console.error(`❌ Worker file not found: ${workerFile}`);
    process.exit(1);
  }
  // Worker needs ALL backend files + rebuild
  const backendDir = join(FEDERATION_DIR, 'federation-game', 'backend');
  const pyFiles = collectPyFiles(backendDir);
  for (const f of pyFiles) {
    const subDir = f.rel.includes('/') ? f.rel.substring(0, f.rel.lastIndexOf('/')) : '';
    deployList.push({
      local: f.local,
      remote: `${VPS_BASE_DIR}/backend/${f.rel.replace(/\\/g, '/')}`,
      restart: 'worker', // only the last one triggers rebuild
      mkdir: subDir ? `${VPS_BASE_DIR}/backend/${subDir.replace(/\\/g, '/')}` : null,
    });
  }
  console.log(`📦 Deploying ${pyFiles.length} backend files (worker rebuild needed)...`);
} else if (target === 'frontend') {
  const frontendDir = join(FEDERATION_DIR, 'federation-game', 'frontend');
  const htmlFiles = readdirSync(frontendDir).filter(f => f.endsWith('.html'));
  for (const f of htmlFiles) {
    deployList.push({
      local: join(frontendDir, f),
      remote: `${VPS_BASE_DIR}/public_html/${f}`,
      restart: 'frontend',
      mkdir: null,
    });
    // Also copy to frontend build context
    deployList.push({
      local: join(frontendDir, f),
      remote: `${VPS_BASE_DIR}/frontend/${f}`,
      restart: 'frontend',
      mkdir: null,
    });
  }
  const staticExts = ['.css', '.js'];
  const staticFiles = readdirSync(frontendDir).filter(f => {
    const ext = '.' + f.split('.').pop();
    return staticExts.includes(ext);
  });
  for (const f of staticFiles) {
    deployList.push({
      local: join(frontendDir, f),
      remote: `${VPS_BASE_DIR}/public_html/${f}`,
      restart: null,
      mkdir: null,
    });
    deployList.push({
      local: join(frontendDir, f),
      remote: `${VPS_BASE_DIR}/frontend/${f}`,
      restart: null,
      mkdir: null,
    });
  }
  console.log(`📦 Deploying ${htmlFiles.length} HTML + ${staticFiles.length} static files (${deployList.length} operations)...`);
} else if (target === 'html' && htmlFile) {
  const frontendDir = join(FEDERATION_DIR, 'federation-game', 'frontend');
  const local = join(frontendDir, htmlFile);
  if (!existsSync(local)) {
    console.error(`❌ File not found: ${local}`);
    process.exit(1);
  }
  deployList.push({ local, remote: `${VPS_BASE_DIR}/public_html/${htmlFile}`, restart: 'frontend', mkdir: null });
  deployList.push({ local, remote: `${VPS_BASE_DIR}/frontend/${htmlFile}`, restart: 'frontend', mkdir: null });
  if (htmlFile.endsWith('.html')) {
    const baseName = htmlFile.slice(0, -'.html'.length);
    for (const ext of ['.css', '.js']) {
      const assetName = `${baseName}${ext}`;
      const assetLocal = join(frontendDir, assetName);
      if (!existsSync(assetLocal)) continue;
      deployList.push({ local: assetLocal, remote: `${VPS_BASE_DIR}/public_html/${assetName}`, restart: null, mkdir: null });
      deployList.push({ local: assetLocal, remote: `${VPS_BASE_DIR}/frontend/${assetName}`, restart: null, mkdir: null });
    }
  }
  console.log(`📦 Deploying ${htmlFile} bundle...`);
} else if (localFile && remotePath) {
  deployList.push({ local: resolve(localFile), remote: remotePath, restart: null, mkdir: null });
  console.log(`📦 Deploying ${localFile} → ${remotePath}...`);
} else {
  console.log(`Usage:
  node deploy.js <local-file> <remote-path>    Deploy a single file
  node deploy.js --target backend              Deploy all backend Python files (recursive)
  node deploy.js --target worker               Deploy backend + rebuild worker Docker
  node deploy.js --target frontend             Deploy all frontend HTML/CSS/JS assets
  node deploy.js --target html --file name.html Deploy one HTML page plus matching CSS/JS
`);
  process.exit(1);
}

// Read SSH key
let privateKey;
try {
  privateKey = readFileSync(VPS_KEY_PATH);
} catch (e) {
  console.error(`❌ Cannot read SSH key at ${VPS_KEY_PATH}: ${e.message}`);
  console.error('Run `node setup-keys.js` first to generate a key pair.');
  process.exit(1);
}

// SSH connect and deploy
function sshExec(conn, cmd) {
  return new Promise((resolve, reject) => {
    conn.exec(cmd, (err, stream) => {
      if (err) return reject(err);
      let stdout = '', stderr = '';
      stream.on('data', d => stdout += d.toString());
      stream.stderr.on('data', d => stderr += d.toString());
      stream.on('close', (code) => {
        if (code !== 0) reject(new Error(`Exit ${code}: ${stderr.trim() || stdout.trim()}`));
        else resolve(stdout.trim());
      });
    });
  });
}

function sshWriteFile(conn, localPath, remotePath) {
  // Use system SSH (scp-style pipe) instead of ssh2 exec for reliable file transfer
  try {
    execFileSync('ssh', [
      '-o', 'StrictHostKeyChecking=accept-new',
      '-i', VPS_KEY_PATH,
      '-p', '22',
      `${VPS_USER}@${VPS_HOST}`,
      `cat > '${remotePath}'`
    ], {
      input: readFileSync(localPath),
      timeout: 30000
    });
    return Promise.resolve();
  } catch (e) {
    return Promise.reject(e);
  }
}

async function run() {
  const conn = new Client();
  
  await new Promise((resolve, reject) => {
    conn.on('ready', resolve);
    conn.on('error', reject);
    conn.connect({
      host: VPS_HOST,
      port: 22,
      username: VPS_USER,
      privateKey,
      readyTimeout: 15000,
    });
  });
  
  console.log(`✅ SSH connected to ${VPS_HOST}`);
  
  try {
    let needsRestart = new Set();
    let dirsCreated = new Set();

    // Ensure remote subdirectories exist (e.g. routes/, data/)
    for (const item of deployList) {
      if (item.mkdir && !dirsCreated.has(item.mkdir)) {
        dirsCreated.add(item.mkdir);
        process.stdout.write(` 📁 mkdir -p ${item.mkdir} ... `);
        await sshExec(conn, `mkdir -p '${item.mkdir}'`);
        console.log('OK');
      }
    }

    for (const item of deployList) {
      const fname = basename(item.local);
      process.stdout.write(` ↑ ${fname} → ${item.remote} ... `);
      await sshWriteFile(conn, item.local, item.remote);
      console.log('OK');
      if (item.restart) needsRestart.add(item.restart);
    }
    
    // Validate Python files if backend/worker was deployed
    if (needsRestart.has('backend') || needsRestart.has('worker')) {
      console.log('\n🔍 Validating Python files on VPS...');
      try {
        await sshExec(conn, `python3 -c "import py_compile; import glob; files=glob.glob('${VPS_BASE_DIR}/backend/*.py')+glob.glob('${VPS_BASE_DIR}/backend/**/*.py',recursive=True); files=list(set(files)); [py_compile.compile(f, doraise=True) for f in files]; print(f'All {len(files)} files valid')"`); 
        console.log(' ✅ All Python files valid');
      } catch (e) {
        console.error(` ❌ Python validation FAILED: ${e.message}`);
        console.error(' 🛑 Aborting restart — fix the errors first');
        conn.end();
        process.exit(1);
      }
    }
    
    // Restart containers
    for (const svc of needsRestart) {
      let cmd;
      if (svc === 'worker') {
        cmd = `cd ${VPS_BASE_DIR} && docker compose build worker && docker compose up -d worker`;
      } else if (svc === 'frontend') {
        cmd = `cd ${VPS_BASE_DIR} && docker compose up -d frontend`;
      } else {
        cmd = `cd ${VPS_BASE_DIR} && docker compose restart ${svc}`;
      }
      console.log(`\n🔄 Restarting ${svc}: ${cmd}`);
      const out = await sshExec(conn, cmd);
      if (out) console.log(` ${out}`);
console.log(` ✅ ${svc} restarted`);
}

if (needsRestart.has('backend')) {
  console.log('\n🧪 Running smoke test...');
  try {
    const smokeOut = await sshExec(
      conn,
      `cd ${VPS_BASE_DIR} && docker exec federation-game-backend-1 python3 /app/smoke_test.py`
    );
    console.log(` ${smokeOut}`);
    console.log(' ✅ Smoke test passed');
  } catch (e) {
    console.error(` ❌ Smoke test FAILED: ${e.message}`);
    console.error(' 🛑 Aborting — backend container left running for debugging');
    conn.end();
    process.exit(1);
  }
}

if (needsRestart.has('worker')) {
  console.log('\n🧪 Running smoke test after worker rebuild...');
  try {
    const smokeOut = await sshExec(
      conn,
      `cd ${VPS_BASE_DIR} && docker exec federation-game-backend-1 python3 /app/smoke_test.py`
    );
    console.log(` ${smokeOut}`);
    console.log(' ✅ Smoke test passed');
  } catch (e) {
    console.error(` ❌ Smoke test FAILED: ${e.message}`);
    console.error(' 🛑 Aborting — check backend logs');
    conn.end();
    process.exit(1);
  }
}

// Verify
    console.log('\n🏥 Verification:');
    try {
      const ps = await sshExec(conn, `cd ${VPS_BASE_DIR} && docker compose ps --format '{{.Name}} {{.Status}}'`);
      console.log(ps.split('\n').map(l => ` ${l}`).join('\n'));
    } catch (e) {
      console.log(` (could not check container status: ${e.message})`);
    }
    try {
      const rootCode = await sshExec(conn, `curl -s -o /dev/null -w '%{http_code}' https://federation-game.deliberatefederation.cloud/`);
      const worldguideCode = await sshExec(conn, `curl -s -o /dev/null -w '%{http_code}' https://federation-game.deliberatefederation.cloud/worldguide.html`);
      const worldguideCssCode = await sshExec(conn, `curl -s -o /dev/null -w '%{http_code}' https://federation-game.deliberatefederation.cloud/worldguide.css`);
      console.log(` Root route: HTTP ${rootCode}`);
      console.log(` World Guide route: HTTP ${worldguideCode}`);
      console.log(` World Guide CSS route: HTTP ${worldguideCssCode}`);
      if (rootCode !== '200' || worldguideCode !== '200' || worldguideCssCode !== '200') {
        throw new Error(`unexpected HTTP status root=${rootCode} worldguide=${worldguideCode} worldguide.css=${worldguideCssCode}`);
      }
    } catch (e) {
      console.error(` ❌ HTTP verification FAILED: ${e.message}`);
      conn.end();
      process.exit(1);
    }
    
    console.log('\n✅ Deployment complete!');
  } catch (e) {
    console.error(`\n❌ Deployment failed: ${e.message}`);
    conn.end();
    process.exit(1);
  }
  
  conn.end();
}

run();
