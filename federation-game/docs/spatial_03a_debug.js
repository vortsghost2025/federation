const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  await page.goto('https://federation-game.deliberatefederation.cloud/starmap.html', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(6000);

  // Inspect JS state
  const state = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const ctx = canvas?.getContext('2d');
    
    // Check all relevant globals
    const info = {
      canvasW: canvas?.width,
      canvasH: canvas?.height,
      canvasStyleW: canvas?.style.width,
      canvasStyleH: canvas?.style.height,
      spatialParam: new URLSearchParams(window.location.search).get('spatial'),
      debugParam: new URLSearchParams(window.location.search).get('debug'),
      globals: {}
    };

    // Check specific functions/vars
    const names = ['getFactionZoneAt', 'toggleFocusFaction', 'rmFocusFactionId', 'selectedFaction',
      'spatialSectors', 'sectors', 'factionZones', 'buildNodesSpatial', 'currentViewMode', 
      'viewMode', 'spatialEnabled', 'SPATIAL_ENABLED', 'toggleStarmapReadableMode',
      'getSectorOwnerId', 'showFactionTip', 'hideFactionTip'];
    
    names.forEach(n => {
      try {
        const val = window[n];
        if (val === undefined) info.globals[n] = 'undefined';
        else if (val === null) info.globals[n] = 'null';
        else if (typeof val === 'function') info.globals[n] = 'function';
        else if (Array.isArray(val)) info.globals[n] = `array[${val.length}]`;
        else if (typeof val === 'object') info.globals[n] = JSON.stringify(val).slice(0, 200);
        else info.globals[n] = String(val).slice(0, 100);
      } catch(e) {
        info.globals[n] = `error: ${e.message}`;
      }
    });

    // Check canvas pixel colors at specific points
    if (ctx && canvas) {
      const w = canvas.width, h = canvas.height;
      const samples = [];
      // Sample a 10x6 grid
      for (let row = 0; row < 6; row++) {
        for (let col = 0; col < 10; col++) {
          const x = Math.round(w * (col + 0.5) / 10);
          const y = Math.round(h * (row + 0.5) / 6);
          const pixel = ctx.getImageData(x, y, 1, 1).data;
          samples.push({ x, y, r: pixel[0], g: pixel[1], b: pixel[2], a: pixel[3] });
        }
      }
      info.pixelSamples = samples;
    }

    return info;
  });

  console.log(JSON.stringify(state, null, 2));

  // Now test clicking using getFactionZoneAt directly
  const clickTest = await page.evaluate(() => {
    const canvas = document.querySelector('canvas');
    const rect = canvas.getBoundingClientRect();
    const results = [];
    
    // Try calling getFactionZoneAt with various mouse positions
    // The function takes (mx, my) which are mouse coordinates relative to canvas
    if (typeof getFactionZoneAt === 'function') {
      const w = rect.width, h = rect.height;
      for (let row = 1; row < 5; row++) {
        for (let col = 1; col < 8; col++) {
          const mx = Math.round(w * col / 8);
          const my = Math.round(h * row / 5);
          const zone = getFactionZoneAt(mx, my);
          if (zone) {
            results.push({ mx, my, zone: JSON.stringify(zone).slice(0, 200) });
          }
        }
      }
    } else {
      results.push({ error: 'getFactionZoneAt not a function' });
    }
    
    return results;
  });

  console.log('\nFaction zone hit test results:');
  console.log(JSON.stringify(clickTest, null, 2));

  // Test toggleFocusFaction
  const toggleTest = await page.evaluate(() => {
    if (typeof toggleFocusFaction === 'function') {
      // Try selecting a faction
      toggleFocusFaction('research_division');
      return { afterSelect: typeof rmFocusFactionId !== 'undefined' ? rmFocusFactionId : 'rmFocusFactionId undefined' };
    }
    return { error: 'toggleFocusFaction not a function' };
  });

  console.log('\nToggle focus faction test:');
  console.log(JSON.stringify(toggleTest, null, 2));

  await browser.close();
})();
