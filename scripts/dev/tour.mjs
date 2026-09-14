import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';
const labels = process.argv.slice(2);
const OUT = process.env.FB_SHOTS || './.shots';
mkdirSync(OUT, { recursive: true });
const b = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox','--use-gl=swiftshader','--enable-unsafe-swiftshader',
         '--disable-dev-shm-usage','--ignore-gpu-blocklist']
});
const p = await b.newPage({ viewport: { width: 1600, height: 950 }, deviceScaleFactor: 1 });
const errs = [];
p.on('pageerror', e => errs.push(`[pageerror] ${e.message}`));
p.on('console', m => { if (m.type()==='error') errs.push(`[console] ${m.text()}`); });
await p.goto('http://127.0.0.1:8099/index.html', { waitUntil: 'networkidle', timeout: 60000 });
await p.waitForTimeout(8000);
for (const label of labels) {
  const before = errs.length;
  try {
    await p.click(`.rail-item:has-text("${label}")`, { timeout: 5000 });
  } catch (e) { console.log(`${label.padEnd(18)} CLICK FAILED`); continue; }
  await p.waitForTimeout(1600);
  const slug = label.toLowerCase().replace(/[^a-z]+/g,'-');
  await p.screenshot({ path: `${OUT}/${slug}.png` });
  const txt = await p.$eval('.page-title', el => el.textContent?.slice(0,50)).catch(()=>'(no .page-title)');
  console.log(`${label.padEnd(18)} title="${txt}" newErrors=${errs.length-before}`);
}
if (errs.length) console.log('--- errors ---\n' + errs.slice(0,25).join('\n'));
await b.close();
