const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, 'simulation.js'), 'utf8');
const context = {
  console,
  URLSearchParams,
  setTimeout,
  clearTimeout,
  document: {
    readyState: 'loading',
    addEventListener() {},
  },
};
context.window = context;

vm.createContext(context);
vm.runInContext(source, context);

const result = context.summarizeNpcLog({
  type: 'interaction',
  actor: 'Chancellor Harmony',
  data: {
    category: 'trade',
    description: 'Chancellor Harmony opened a resource trade',
    target_char_id: 'comp_009',
    target_name: 'Brother Mercy',
    relationship_delta: 2.6,
  },
});

assert.match(result.summary, /Brother Mercy/);
assert.match(result.why, /Relationship \+2\.6/);

console.log('NPC reality summary tests passed.');
