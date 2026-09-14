import { chromium } from 'playwright-core';
const b = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox','--use-gl=swiftshader','--enable-unsafe-swiftshader','--disable-dev-shm-usage']
});
const p = await b.newPage({ viewport: { width: 1200, height: 800 } });
p.on('pageerror', e => console.log('[pageerror]', e.message));
await p.goto('http://127.0.0.1:8099/index.html', { waitUntil: 'networkidle', timeout: 60000 });
await p.waitForTimeout(8000);
const out = await p.evaluate(() => {
  const s = window.__fb.state; const now = s.now; const D = 86400000;
  const buckets = {};
  s.trips.forEach(t => { const d = Math.floor((now - t.startedAt)/D); buckets[d] = (buckets[d]||0)+1; });
  const days = Object.keys(buckets).map(Number).sort((a,b)=>a-b);
  const dist = s.trips.map(t=>t.distanceKm).sort((a,b)=>a-b);
  return {
    dayMin: days[0], dayMax: days[days.length-1], distinctDays: days.length,
    first20: days.slice(0,20).map(d=>`${d}:${buckets[d]}`),
    distMin: dist[0], distMedian: dist[Math.floor(dist.length/2)], distMax: dist[dist.length-1],
    zeroDist: dist.filter(x=>x===0).length,
    customerCoords: s.customers.slice(0,4).map(c => { const pl = s.places.find(p=>p.id===c.placeId); return pl? [pl.lat, pl.lon] : null; }),
  };
});
console.log(JSON.stringify(out, null, 2));
await b.close();
