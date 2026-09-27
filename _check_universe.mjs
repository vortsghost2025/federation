import { readFileSync } from 'fs';

const html = readFileSync('federation-game/frontend/universe.html', 'utf8');

// Extract module script
const start = html.indexOf('<script type="module">') + '<script type="module">'.length;
const end = html.indexOf('</script>', start);
const js = html.substring(start, end);

// Basic syntax check: strip imports, wrap in async function to validate
const strippedJs = js.split('\n').filter(l => !l.trim().startsWith('import ')).join('\n');
try {
  new Function(strippedJs);
  console.log('JS SYNTAX: PASS - No parse errors (import-stripped)');
} catch (e) {
  console.log('JS SYNTAX: FAIL');
  console.log('  ' + e.message);
}

// Check importmap
const imStart = html.indexOf('<script type="importmap">') + '<script type="importmap">'.length;
const imEnd = html.indexOf('</script>', imStart);
const importmap = JSON.parse(html.substring(imStart, imEnd));
console.log('\nIMPORTMAP entries:', JSON.stringify(importmap.imports, null, 2));

// Check imports in code
const importLines = js.split('\n').filter(l => l.trim().startsWith('import'));
console.log('\nIMPORT statements:');
importLines.forEach(l => console.log('  ' + l.trim()));

// Check for undefined references to common issues
const usesOutputPass = js.includes('OutputPass');
const usesCopyShader = js.includes('CopyShader');
console.log('\nPostprocessing usage:');
console.log('  OutputPass used:', usesOutputPass);
console.log('  CopyShader used:', usesCopyShader, usesCopyShader ? '(NEEDS IMPORT!)' : '(not needed)');

// Check Three.js API usage
const apis = ['TubeGeometry', 'CatmullRomCurve3', 'InstancedMesh', 'ShaderMaterial', 'Points',
  'BufferGeometry', 'BufferAttribute', 'WebGLRenderer', 'LinearSRGBColorSpace', 'ACESFilmicToneMapping'];
console.log('\nThree.js API usage:');
apis.forEach(api => {
  if (js.includes(api)) console.log(`  ${api}: USED`);
});

// Check Clock usage pattern: same line with both calls AND getDelta() AFTER getElapsedTime() = BUG
if (js.includes('clock.getElapsedTime()') && js.includes('clock.getDelta()')) {
  const lines = js.split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.includes('getElapsedTime') && line.includes('getDelta')) {
      const elapsedIdx = line.indexOf('getElapsedTime');
      const deltaIdx = line.indexOf('getDelta');
      if (deltaIdx > elapsedIdx) {
        console.log(`\nBUG at module-line ${i+1}: getDelta() called AFTER getElapsedTime() on the same line.`);
        console.log('  getElapsedTime() internally calls getDelta() first, so the trailing getDelta() returns ~0.');
        console.log('  Result: dt-based animations (NPC orbits, ring rotation, camera) are nearly static.');
        console.log('  FIX: Swap order to: const dt = clock.getDelta(), t = clock.getElapsedTime();');
      } else {
        console.log(`\nOK at module-line ${i+1}: getDelta() is called BEFORE getElapsedTime() (correct order).`);
      }
    }
  }
}
