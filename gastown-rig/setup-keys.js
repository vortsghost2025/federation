/**
 * setup-keys.js — Generate RSA SSH key pair for Gastown rig
 * 
 * Uses PKCS1 PEM format which ssh2 library supports natively.
 * RSA is chosen over ed25519 because ssh2's ed25519 OpenSSH key
 * parsing is unreliable with Node.js crypto output.
 * 
 * Run: node setup-keys.js
 * 
 * Generates:
 *   ~/.ssh/id_rsa      (PKCS1 PEM private key — works with ssh2)
 *   ~/.ssh/id_rsa.pub  (OpenSSH format public key — works with sshd)
 * 
 * Prints the public key to add to VPS authorized_keys.
 */
import { generateKeyPairSync } from 'node:crypto';
import { writeFileSync, mkdirSync, existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

const sshDir = join(homedir(), '.ssh');
const keyPath = join(sshDir, 'id_rsa');
const pubPath = keyPath + '.pub';

// Already exists?
if (existsSync(keyPath) && existsSync(pubPath)) {
  console.log('🔑 SSH key already exists:');
  console.log(`  Private: ${keyPath}`);
  console.log(`  Public:  ${pubPath}`);
  console.log(`\n  ${readFileSync(pubPath, 'utf8').trim()}`);
  console.log('\nIf this key is already on the VPS, you are good to go.');
  console.log('If not, add the public key to VPS authorized_keys (see below).');
  process.exit(0);
}

// Ensure .ssh directory exists
mkdirSync(sshDir, { recursive: true });

// Generate RSA 4096 key pair in PKCS1 PEM format
// PKCS1 is the "-----BEGIN RSA PRIVATE KEY-----" format that ssh2 expects
const { publicKey, privateKey } = generateKeyPairSync('rsa', {
  modulusLength: 4096,
  publicKeyEncoding: {
    type: 'spki',
    format: 'pem'
  },
  privateKeyEncoding: {
    type: 'pkcs1',    // <-- THIS IS KEY: pkcs1, not pkcs8
    format: 'pem'
  }
});

// Convert PEM public key to OpenSSH format
// ssh2 can do this for us — parse the PEM and export as OpenSSH
// But we're not importing ssh2 here, so we do it manually:
// The OpenSSH public key format is: "ssh-rsa <base64blob> comment"
// The base64blob is: uint32(len("ssh-rsa")) + "ssh-rsa" + uint32(exponent_len) + exponent + uint32(modulus_len) + modulus
import { createPublicKey } from 'node:crypto';

const pubKeyObj = createPublicKey(publicKey);
const pubDer = pubKeyObj.export({ type: 'spki', format: 'der' });

// Parse the DER-encoded SPKI public key to extract RSA exponent and modulus
// SPKI format: SEQUENCE { AlgorithmIdentifier, BIT STRING { SEQUENCE { INTEGER(exponent), INTEGER(modulus) } } }
function extractRsaFromSpki(der) {
  // Walk the DER structure to find the BIT STRING containing the RSA public key
  let offset = 0;
  
  function readTag() { return der[offset++]; }
  function readLen() {
    const b = der[offset++];
    if (b < 128) return b;
    const numBytes = b & 0x7f;
    let len = 0;
    for (let i = 0; i < numBytes; i++) len = (len << 8) | der[offset++];
    return len;
  }
  function skipValue() {
    readTag();
    const len = readLen();
    offset += len;
  }
  function readInteger() {
    const tag = readTag();
    if (tag !== 0x02) throw new Error(`Expected INTEGER tag 0x02, got 0x${tag.toString(16)}`);
    const len = readLen();
    // DER integers may have a leading zero byte if the high bit is set
    let bytes = der.subarray(offset, offset + len);
    offset += len;
    // Strip leading zero byte (sign byte)
    if (bytes[0] === 0 && bytes.length > 1) bytes = bytes.subarray(1);
    return bytes;
  }
  
  // Outer SEQUENCE
  readTag(); readLen();
  // AlgorithmIdentifier SEQUENCE
  skipValue();
  // BIT STRING
  readTag(); // 0x03
  const bitLen = readLen();
  const unusedBits = der[offset++]; // should be 0
  
  // Inside BIT STRING: SEQUENCE { INTEGER(exponent), INTEGER(modulus) }
  readTag(); readLen(); // inner SEQUENCE
  const exponent = readInteger();
  const modulus = readInteger();
  
  return { exponent, modulus };
}

function uint32BE(n) {
  const buf = Buffer.alloc(4);
  buf.writeUInt32BE(n);
  return buf;
}

function sshString(str) {
  if (typeof str === 'string') str = Buffer.from(str);
  return Buffer.concat([uint32BE(str.length), str]);
}

try {
  const { exponent, modulus } = extractRsaFromSpki(pubDer);
  
  // Build OpenSSH public key blob
  const blob = Buffer.concat([
    sshString('ssh-rsa'),
    sshString(exponent),
    sshString(modulus)
  ]);
  
  const pubLine = `ssh-rsa ${blob.toString('base64')} gastown-rig`;
  
  // Write keys
  writeFileSync(keyPath, privateKey, { mode: 0o600 });
  writeFileSync(pubPath, pubLine + '\n', { mode: 0o644 });
  
  console.log('✅ Generated RSA 4096 SSH key pair (PKCS1 PEM format):');
  console.log(`  Private: ${keyPath}`);
  console.log(`  Public:  ${pubPath}`);
  console.log(`\n  ${pubLine}`);
  console.log('\n📎 Add this public key to VPS authorized_keys:');
  console.log('  (run from the rig after connecting, or paste it manually)');
  console.log(`\n  ssh root@187.77.3.56 "echo '${pubLine}' >> /root/.ssh/authorized_keys"`);
  console.log('\n💡 Then test: node shell.js --cmd hostname');
} catch (e) {
  console.error('❌ Key generation failed:', e.message);
  process.exit(1);
}
