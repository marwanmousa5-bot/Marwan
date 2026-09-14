import { chromium } from 'playwright-core';
const b = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox','--use-gl=swiftshader','--enable-unsafe-swiftshader','--disable-dev-shm-usage']
});
const p = await b.newPage({ viewport: { width: 1500, height: 900 } });
p.on('response', r => { if (r.status() >= 400) console.log(`[HTTP ${r.status()}] ${r.url()}`); });
p.on('console', m => { const t = m.text(); if (!t.includes('GL Driver')) console.log(`[${m.type()}] ${t}`); });
p.on('pageerror', e => console.log(`[pageerror] ${e.message}`));
await p.goto(process.argv[2], { waitUntil: 'load', timeout: 60000 });
await p.waitForTimeout(12000);
const diag = await p.evaluate(() => {
  const cv = document.querySelector('canvas');
  const holder = document.querySelector('.map-canvas');
  const area = document.querySelector('.map-area');
  const m = document.querySelector('.veh-marker');
  return {
    canvas: cv ? { w: cv.width, h: cv.height, cw: cv.clientWidth, ch: cv.clientHeight } : null,
    holder: holder ? { w: holder.clientWidth, h: holder.clientHeight, cls: holder.className } : null,
    area: area ? { w: area.clientWidth, h: area.clientHeight } : null,
    markerParent: m ? (m.parentElement?.getAttribute('style') || 'no-style') : 'none',
    markerVisible: m ? m.getBoundingClientRect().width : -1,
  };
});
console.log('DIAG', JSON.stringify(diag, null, 1));
await b.close();
