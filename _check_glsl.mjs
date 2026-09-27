import { readFileSync } from 'fs';
const html = readFileSync('federation-game/frontend/universe.html', 'utf8');
const start = html.indexOf('<script type="module">') + 22;
const end = html.indexOf('</script>', start);
const js = html.substring(start, end);

// Find all template literal strings that look like GLSL
const backtickStrings = js.match(/`[^`]*`/g) || [];
let glslCount = 0;
backtickStrings.forEach((s) => {
  if (s.includes('gl_') || s.includes('void main') || s.includes('uniform')) {
    glslCount++;
    const hasMain = s.includes('void main');
    const hasGlPos = s.includes('gl_Position');
    const hasGlFrag = s.includes('gl_FragColor');
    const hasVarying = s.includes('varying');
    const hasUniform = s.includes('uniform');
    console.log(`GLSL #${glslCount}: ${hasMain ? 'has main()' : 'NO main()'} ${hasGlPos ? '[vertex]' : ''} ${hasGlFrag ? '[fragment]' : ''}`);
    
    // Check for common GLSL errors
    const braces = (s.match(/{/g) || []).length - (s.match(/}/g) || []).length;
    if (braces !== 0) console.log(`  ERROR: Unbalanced braces (diff: ${braces})`);
    const parens = (s.match(/\(/g) || []).length - (s.match(/\)/g) || []).length;
    if (parens !== 0) console.log(`  ERROR: Unbalanced parentheses (diff: ${parens})`);
    
    // Check semicolons after statements
    if (hasMain && !s.includes(';')) console.log('  WARNING: No semicolons found');
  }
});
console.log(`\nTotal GLSL shaders in template literals: ${glslCount}`);

// Also check the object-based shader (filmGrainShader)
const filmGrainMatch = js.match(/filmGrainShader\s*=\s*\{[\s\S]*?\n\};/);
if (filmGrainMatch) {
  console.log('\nfilmGrainShader object: FOUND');
  const vertMatch = filmGrainMatch[0].match(/vertexShader:\s*`([^`]*)`/);
  const fragMatch = filmGrainMatch[0].match(/fragmentShader:\s*`([^`]*)`/);
  if (vertMatch) {
    const v = vertMatch[1];
    console.log('  vertexShader: ' + (v.includes('gl_Position') ? 'has gl_Position' : 'MISSING gl_Position'));
  }
  if (fragMatch) {
    const f = fragMatch[1];
    console.log('  fragmentShader: ' + (f.includes('gl_FragColor') ? 'has gl_FragColor' : 'MISSING gl_FragColor'));
  }
}
