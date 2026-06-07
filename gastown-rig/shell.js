/**
 * shell.js — Run a single command on the Federation VPS via SSH (ssh2)
 * 
 * Usage:
 *   node shell.js --cmd "hostname"
 *   node shell.js --cmd "cd /docker/federation-game && docker compose ps"
 *   node shell.js --cmd "docker logs --tail=20 federation-game-backend-1"
 * 
 * Environment:
 * VPS_HOST - VPS IP (default: 187.77.3.56)
 * VPS_USER - SSH user (default: root)
 * VPS_KEY_PATH - Path to SSH private key (default: ~/.ssh/id_ed25519)
 */
import { Client } from 'ssh2';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

const VPS_HOST = process.env.VPS_HOST || '187.77.3.56';
const VPS_USER = process.env.VPS_USER || 'root';
const VPS_KEY_PATH = process.env.VPS_KEY_PATH || join(homedir(), '.ssh', 'id_rsa');

// Parse --cmd argument
const cmdIdx = process.argv.indexOf('--cmd');
if (cmdIdx === -1 || !process.argv[cmdIdx + 1]) {
  console.log('Usage: node shell.js --cmd "command to run on VPS"');
  process.exit(1);
}
const cmd = process.argv.slice(cmdIdx + 1).join(' ');

// Read SSH key
let privateKey;
try {
  privateKey = readFileSync(VPS_KEY_PATH);
} catch (e) {
  console.error(`❌ Cannot read SSH key at ${VPS_KEY_PATH}: ${e.message}`);
  process.exit(1);
}

const conn = new Client();
conn.on('ready', () => {
  conn.exec(cmd, (err, stream) => {
    if (err) {
      console.error(`Exec error: ${err.message}`);
      conn.end();
      process.exit(1);
    }
    let stdout = '', stderr = '';
    stream.on('data', d => { stdout += d.toString(); process.stdout.write(d); });
    stream.stderr.on('data', d => { stderr += d.toString(); process.stderr.write(d); });
    stream.on('close', (code) => {
      conn.end();
      process.exit(code);
    });
  });
});

conn.on('error', (e) => {
  console.error(`SSH connection error: ${e.message}`);
  process.exit(1);
});

conn.connect({
  host: VPS_HOST,
  port: 22,
  username: VPS_USER,
  privateKey,
  readyTimeout: 15000,
});
