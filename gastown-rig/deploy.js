/**
 * deploy.js — Deploy files from Gastown rig to Federation VPS via SSH (ssh2)
 * 
 * Usage:
 *   node deploy.js <local-file> <remote-path>              Deploy a single file
 *   node deploy.js --target backend                         Deploy all backend Python files
 *   node deploy.js --target worker                          Deploy worker + rebuild Docker image
 *   node deploy.js --target frontend                        Deploy all frontend HTML files
 *   node deploy.js --target html                            Deploy a single HTML file (needs --file flag)
 *   node deploy.js --target html --file simulation.html     Deploy simulation.html only
 * 
 * Environment:
 * VPS_HOST - VPS IP (default: 187.77.3.56)
 * VPS_USER - SSH user (default: root)
 * VPS_KEY_PATH - Path to SSH private key (default: ~/.ssh/id_rsa)
 * FEDERATION_DIR - Project root on rig (default: current directory)
 * VPS_BASE_DIR - Project root on VPS (default: /docker/federation-game)
 */
import { connect } from 'ssh2';
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs';
import { join, basename, resolve } from 'node:path';
import { homedir } from 'node:os';

const VPS_HOST = process.env.VPS_HOST || '187.77.3.56';
const VPS_USER = process.env.VPS_USER || 'root';
const VPS_KEY_PATH = process.env.VPS_KEY_PATH || join(homedir(), '.ssh', 'id_rsa');
const FEDERATION_DIR = process.env.FEDERATION_DIR || process.cwd();
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

// Determine files to deploy
let deployList = []; // [{local, remote, restart}]

if (target === 'backend') {
  const backendDir = join(FEDERATION_DIR, 'federation-game', 'backend');
  if (!existsSync(backendDir)) {
    console.error(`❌ Backend dir not found: ${backendDir}`);
    process.exit(1);
  }
  const pyFiles = readdirSync(backendDir).filter(f => f.endsWith('.py'));
  for (const f of pyFiles) {
    deployList.push({
      local: join(backendDir, f),
      remote: `${VPS_BASE_DIR}/backend/${f}`,
      restart: 'backend'
    });
  }
  console.log(`📦 Deploying ${pyFiles.length} backend files...`);
} else if (target === 'worker') {
  const workerFile = join(FEDERATION_DIR, 'federation-game', 'backend', 'worker.py');
  if (!existsSync(workerFile)) {
    console.error(`❌ Worker file not found: ${workerFile}`);
    process.exit(1);
  }
  // Worker needs ALL backend files + rebuild
  const backendDir = join(FEDERATION_DIR, 'federation-game', 'backend');
  const pyFiles = readdirSync(backendDir).filter(f => f.endsWith('.py'));
  for (const f of pyFiles) {
    deployList.push({
      local: join(backendDir, f),
      remote: `${VPS_BASE_DIR}/backend/${f}`,
      restart: 'worker' // only the last one triggers rebuild
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
      restart: 'frontend'
    });
    // Also copy to frontend build context
    deployList.push({
      local: join(frontendDir, f),
      remote: `${VPS_BASE_DIR}/frontend/${f}`,
      restart: 'frontend'
    });
  }
  console.log(`📦 Deploying ${htmlFiles.length} HTML files (${deployList.length} operations)...`);
} else if (target === 'html' && htmlFile) {
  const frontendDir = join(FEDERATION_DIR, 'federation-game', 'frontend');
  const local = join(frontendDir, htmlFile);
  if (!existsSync(local)) {
    console.error(`❌ File not found: ${local}`);
    process.exit(1);
  }
  deployList.push({ local, remote: `${VPS_BASE_DIR}/public_html/${htmlFile}`, restart: 'frontend' });
  deployList.push({ local, remote: `${VPS_BASE_DIR}/frontend/${htmlFile}`, restart: 'frontend' });
  console.log(`📦 Deploying ${htmlFile}...`);
} else if (localFile && remotePath) {
  deployList.push({ local: resolve(localFile), remote: remotePath, restart: null });
  console.log(`📦 Deploying ${localFile} → ${remotePath}...`);
} else {
  console.log(`Usage:
  node deploy.js <local-file> <remote-path>         Deploy a single file
  node deploy.js --target backend                    Deploy all backend Python files
  node deploy.js --target worker                     Deploy backend + rebuild worker Docker
  node deploy.js --target frontend                   Deploy all HTML files
  node deploy.js --target html --file name.html      Deploy one HTML file
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
  return new Promise((resolve, reject) => {
    const content = readFileSync(localPath);
    const cmd = `cat > '${remotePath}'`;
    conn.exec(cmd, (err, stream) => {
      if (err) return reject(err);
      let stderr = '';
      stream.stderr.on('data', d => stderr += d.toString());
      stream.on('close', (code) => {
        if (code !== 0) reject(new Error(`Write failed exit ${code}: ${stderr.trim()}`));
        else resolve();
      });
      stream.write(content);
      stream.end();
    });
  });
}

async function run() {
  const conn = new connect();
  
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
    
    for (const item of deployList) {
      const fname = basename(item.local);
      process.stdout.write(`   ↑ ${fname} → ${item.remote} ... `);
      await sshWriteFile(conn, item.local, item.remote);
      console.log('OK');
      if (item.restart) needsRestart.add(item.restart);
    }
    
    // Validate Python files if backend/worker was deployed
    if (needsRestart.has('backend') || needsRestart.has('worker')) {
      console.log('\n🔍 Validating Python files on VPS...');
      try {
        await sshExec(conn, `python3 -c "import py_compile; import glob; files=glob.glob('${VPS_BASE_DIR}/backend/*.py'); [py_compile.compile(f, doraise=True) for f in files]; print(f'All {len(files)} files valid')"`); 
        console.log('   ✅ All Python files valid');
      } catch (e) {
        console.error(`   ❌ Python validation FAILED: ${e.message}`);
        console.error('   🛑 Aborting restart — fix the errors first');
        conn.end();
        process.exit(1);
      }
    }
    
    // Restart containers
    for (const svc of needsRestart) {
      let cmd;
      if (svc === 'worker') {
        cmd = `cd ${VPS_BASE_DIR} && docker compose build worker && docker compose up -d worker`;
      } else {
        cmd = `cd ${VPS_BASE_DIR} && docker compose restart ${svc}`;
      }
      console.log(`\n🔄 Restarting ${svc}: ${cmd}`);
      const out = await sshExec(conn, cmd);
      if (out) console.log(`   ${out}`);
      console.log(`   ✅ ${svc} restarted`);
    }
    
    // Verify
    console.log('\n🏥 Verification:');
    try {
      const ps = await sshExec(conn, `cd ${VPS_BASE_DIR} && docker compose ps --format '{{.Name}} {{.Status}}'`);
      console.log(ps.split('\n').map(l => `   ${l}`).join('\n'));
    } catch (e) {
      console.log(`   (could not check container status: ${e.message})`);
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
