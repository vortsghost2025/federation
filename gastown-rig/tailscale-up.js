/**
 * tailscale-up.js — Bring Tailscale up, run a command, then bring it down
 * 
 * Since tailscaled dies after 120s bash timeout on the rig, this script
 * brings up Tailscale, runs your deployment, then takes it back down.
 * 
 * Usage:
 *   node tailscale-up.js node deploy.js --target backend
 *   node tailscale-up.js node shell.js --cmd "docker compose ps"
 * 
 * Requires: tailscale binary installed on the rig
 * 
 * Environment:
 *   TS_AUTHKEY    - Tailscale auth key (or pass via --authkey flag)
 *   TS_HOSTNAME   - Tailscale hostname (default: gastown-rig)
 */
import { execSync, spawn } from 'node:child_process';

const TS_AUTHKEY = process.env.TS_AUTHKEY || findArg('--authkey');
const TS_HOSTNAME = process.env.TS_HOSTNAME || 'gastown-rig';
const command = process.argv.slice(2).filter(a => !a.startsWith('--authkey')).join(' ');

function findArg(name) {
  const idx = process.argv.indexOf(name);
  return idx !== -1 ? process.argv[idx + 1] : null;
}

if (!command) {
  console.log('Usage: node tailscale-up.js <command to run while Tailscale is up>');
  console.log('Example: node tailscale-up.js node deploy.js --target backend');
  process.exit(1);
}

if (!TS_AUTHKEY) {
  console.error('❌ No Tailscale auth key. Set TS_AUTHKEY env var or use --authkey flag.');
  process.exit(1);
}

console.log('🔗 Bringing Tailscale up...');

try {
  // Start tailscaled in background
  execSync('tailscaled --state=/tmp/tailscale.state --socket=/tmp/tailscaled.sock &', {
    stdio: 'pipe',
    timeout: 5000
  });
} catch (e) {
  // Might already be running, that's ok
}

// Wait for socket
let retries = 10;
while (retries-- > 0) {
  try {
    execSync('test -S /tmp/tailscaled.sock', { stdio: 'pipe' });
    break;
  } catch {
    execSync('sleep 1', { stdio: 'pipe' });
  }
}

// Bring up Tailscale
try {
  const upCmd = `tailscale up --authkey=${TS_AUTHKEY} --hostname=${TS_HOSTNAME} --accept-routes`;
  console.log(`   Running: ${upCmd.replace(TS_AUTHKEY, 'tskey-***')}`);
  execSync(upCmd, { stdio: 'inherit', timeout: 30000 });
  console.log('✅ Tailscale is up');
} catch (e) {
  console.error('❌ Tailscale up failed:', e.message);
  process.exit(1);
}

// Run the actual command
console.log(`\n🚀 Running: ${command}\n`);
try {
  const child = spawn(command, [], { stdio: 'inherit', shell: true });
  child.on('exit', (code) => {
    // Take Tailscale down
    console.log('\n🔗 Taking Tailscale down...');
    try { execSync('tailscale down', { stdio: 'pipe' }); } catch {}
    process.exit(code);
  });
} catch (e) {
  console.error('❌ Command failed:', e.message);
  try { execSync('tailscale down', { stdio: 'pipe' }); } catch {}
  process.exit(1);
}
