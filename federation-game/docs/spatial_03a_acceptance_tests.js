const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  
  const results = [];
  const log = (name, pass, detail) => {
    const status = pass ? 'PASS' : 'FAIL';
    results.push({ name, pass, detail });
    console.log(`[${status}] ${name}: ${detail}`);
  };

  try {
    const consoleErrors = [];
    page.on('console', msg => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
    page.on('pageerror', err => consoleErrors.push(err.message));

    await page.goto('https://federation-game.deliberatefederation.cloud/starmap.html', { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(6000);

    log('Starmap loads without JS errors', consoleErrors.length === 0,
      consoleErrors.length === 0 ? 'No console errors' : `${consoleErrors.length} errors: ${consoleErrors.slice(0,5).join('; ')}`);

    const canvasInfo = await page.evaluate(() => {
      const canvas = document.querySelector('canvas');
      if (!canvas) return { exists: false };
      return { exists: true, w: canvas.width, h: canvas.height };
    });
    log('Canvas element exists', canvasInfo.exists, canvasInfo.exists ? `${canvasInfo.w}x${canvasInfo.h}` : 'Missing');

    // TEST: Faction zones found via getFactionZoneAt
    const zoneTest = await page.evaluate(() => {
      if (typeof getFactionZoneAt !== 'function') return { error: 'getFactionZoneAt not defined' };
      const canvas = document.querySelector('canvas');
      const rect = canvas.getBoundingClientRect();
      const W = rect.width, H = rect.height;
      const foundFactions = new Set();
      const details = [];
      for (let x = 20; x < W; x += 40) {
        for (let y = 20; y < H; y += 40) {
          const zone = getFactionZoneAt(x, y);
          if (zone && !foundFactions.has(zone.fid)) {
            foundFactions.add(zone.fid);
            const cx = W/2, cy = H/2;
            const dist = Math.sqrt((zone.fcx - cx)**2 + (zone.fcy - cy)**2);
            const maxDist = Math.sqrt(cx*cx + cy*cy);
            details.push({ fid: zone.fid, name: zone.fdata?.display_name || zone.fid, cx: Math.round(zone.fcx), cy: Math.round(zone.fcy), pctOfMax: Math.round(dist/maxDist*100) });
          }
        }
      }
      return { count: foundFactions.size, factions: [...foundFactions], details };
    });

    log('Faction zones found via getFactionZoneAt', zoneTest.count >= 3,
      `Found ${zoneTest.count}/8: [${zoneTest.factions?.join(', ')}]`);

    log('At least 6 distinct faction zones on map', zoneTest.count >= 6,
      `Positions: ${zoneTest.details?.map(z => `${z.fid}(${z.pctOfMax}%)`).join(', ')}`);

    log('Faction zones spread across map (>30% from center)', 
      zoneTest.details?.filter(z => z.pctOfMax > 30).length >= 3,
      `Far zones: ${zoneTest.details?.filter(z => z.pctOfMax > 30).length}, Details: ${JSON.stringify(zoneTest.details)}`);

    // TEST: View mode buttons
    const viewButtons = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll('button'));
      return buttons.filter(b => /territory|network|crisis/i.test(b.textContent || '')).map(b => b.textContent.trim());
    });
    log('View mode buttons exist', viewButtons.length >= 3, `Found: ${viewButtons.join(', ')}`);

    // TEST: FIT button
    const fitBtn = await page.$('button:has-text("FIT")');
    log('FIT button exists', !!fitBtn, fitBtn ? 'Found' : 'Missing');
    if (fitBtn) {
      await fitBtn.click();
      await page.waitForTimeout(500);
    }

    // TEST: Content renders on canvas after FIT
    const contentCheck = await page.evaluate(() => {
      const canvas = document.querySelector('canvas');
      if (!canvas) return 0;
      const ctx = canvas.getContext('2d');
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let count = 0;
      for (let i = 3; i < data.length; i += 16) { if (data[i] > 50) count++; }
      return count;
    });
    log('Canvas renders visible content', contentCheck > 500, `Content pixels: ${contentCheck}`);

    // TEST: Color diversity in canvas
    const colorDiversity = await page.evaluate(() => {
      const canvas = document.querySelector('canvas');
      if (!canvas) return { error: 'no canvas' };
      const ctx = canvas.getContext('2d');
      const w = canvas.width, h = canvas.height;
      const data = ctx.getImageData(0, 0, w, h).data;
      const hueBuckets = {};
      for (let row = 0; row < 12; row++) {
        for (let col = 0; col < 20; col++) {
          const x = Math.round(w * (col + 0.5) / 20);
          const y = Math.round(h * (row + 0.5) / 12);
          const idx = (y * w + x) * 4;
          const r = data[idx], g = data[idx+1], b = data[idx+2], a = data[idx+3];
          if (a > 100) {
            const maxC = Math.max(r,g,b), minC = Math.min(r,g,b);
            const sat = maxC > 0 ? (maxC - minC)/maxC : 0;
            if (sat < 0.15) continue;
            let hue = 0;
            if (maxC !== minC) {
              if (maxC === r) hue = ((g - b)/(maxC-minC))*60;
              else if (maxC === g) hue = (2+(b-r)/(maxC-minC))*60;
              else hue = (4+(r-g)/(maxC-minC))*60;
              if (hue < 0) hue += 360;
            }
            const bucket = Math.round(hue/30)*30;
            hueBuckets[bucket] = (hueBuckets[bucket]||0) + 1;
          }
        }
      }
      return { distinctHues: Object.keys(hueBuckets).length, distribution: hueBuckets };
    });
    log('Multiple distinct faction color hues visible', colorDiversity.distinctHues >= 3,
      `${colorDiversity.distinctHues} hue groups: ${JSON.stringify(colorDiversity.distribution)}`);

    // TEST: Legacy fallback
    const page2 = await context.newPage();
    const legacyErrors = [];
    page2.on('console', msg => { if (msg.type() === 'error') legacyErrors.push(msg.text()); });
    page2.on('pageerror', err => legacyErrors.push(err.message));
    await page2.goto('https://federation-game.deliberatefederation.cloud/starmap.html?spatial=false', { waitUntil: 'networkidle', timeout: 30000 });
    await page2.waitForTimeout(5000);
    const legacyCanvas = await page2.evaluate(() => !!document.querySelector('canvas'));
    log('Legacy fallback (?spatial=false) loads', legacyCanvas && legacyErrors.length === 0,
      `Canvas: ${legacyCanvas}, Errors: ${legacyErrors.length}`);
    await page2.close();

    // TEST: toggleFocusFaction doesn't crash (the drawMap bug we fixed)
    const toggleTest = await page.evaluate(() => {
      try {
        if (typeof toggleFocusFaction === 'function') {
          toggleFocusFaction();
          return { ok: true, focusId: rmFocusFactionId };
        }
        return { ok: false, error: 'toggleFocusFaction not a function' };
      } catch(e) {
        return { ok: false, error: e.message };
      }
    });
    log('toggleFocusFaction does not crash', toggleTest.ok,
      toggleTest.ok ? `Focus set to: ${toggleTest.focusId}` : `Error: ${toggleTest.error}`);

    // Reset focus
    await page.keyboard.press('Escape');
    await page.waitForTimeout(200);

  } catch (err) {
    log('Test runner', false, `Fatal error: ${err.message}`);
  } finally {
    await browser.close();
  }

  const passed = results.filter(r => r.pass).length;
  const failed = results.filter(r => !r.pass).length;
  console.log(`\n=== SUMMARY: ${passed} PASSED, ${failed} FAILED ===`);
  if (failed > 0) {
    console.log('FAILURES:');
    results.filter(r => !r.pass).forEach(r => console.log(`  - ${r.name}: ${r.detail}`));
  }
})();
