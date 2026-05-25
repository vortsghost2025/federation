/**
 * sync-state.js — Write/Read session state for Gastown rig
 * 
 * Usage:
 *   node sync-state.js save "Current task description" "What I found" "What's next"
 *   node sync-state.js load              # Print last saved state
 *   node sync-state.js update "new finding"  # Append to findings
 * 
 * State file: ./GASTOWN_STATE.json (persists between sessions)
 */
import { writeFileSync, readFileSync, existsSync } from 'node:fs';

const STATE_FILE = './GASTOWN_STATE.json';

function loadState() {
  if (!existsSync(STATE_FILE)) return null;
  try {
    return JSON.parse(readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return null;
  }
}

function saveState(task, findings, nextSteps) {
  const prev = loadState();
  const state = {
    updated: new Date().toISOString(),
    session_count: (prev?.session_count || 0) + 1,
    current_task: task,
    findings: findings ? [findings] : [],
    next_steps: nextSteps || [],
    history: prev ? [...(prev.history || []).slice(-9), {
      task: prev.current_task,
      findings: prev.findings,
      timestamp: prev.updated
    }] : []
  };
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
  console.log('✅ State saved:', STATE_FILE);
  console.log(JSON.stringify(state, null, 2));
}

const action = process.argv[2];

if (action === 'save') {
  saveState(process.argv[3], process.argv[4], process.argv[5]?.split(';'));
} else if (action === 'load') {
  const state = loadState();
  if (!state) {
    console.log('No previous state found. Fresh start.');
  } else {
    console.log(JSON.stringify(state, null, 2));
  }
} else if (action === 'update') {
  const prev = loadState();
  if (!prev) {
    console.log('No state to update. Run save first.');
    process.exit(1);
  }
  prev.findings.push(process.argv[3]);
  prev.updated = new Date().toISOString();
  writeFileSync(STATE_FILE, JSON.stringify(prev, null, 2));
  console.log('✅ Finding added:', process.argv[3]);
} else {
  console.log('Usage:');
  console.log('  node sync-state.js save "task" "finding" "next1;next2;next3"');
  console.log('  node sync-state.js load');
  console.log('  node sync-state.js update "new finding to append"');
}
