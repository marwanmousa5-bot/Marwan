import { chromium } from 'playwright-core';
const url = process.argv[2];
const out = process.argv[3];
const wait = parseInt(process.argv[4] || '9000', 10);
const b = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox','--use-gl=swiftshader','--enable-unsafe-swiftshader',
         '--disable-dev-shm-usage','--ignore-gpu-blocklist']
});
const p = await b.newPage({ viewport: { width: 1600, height: 950 }, deviceScaleFactor: 2 });
const msgs = [];
p.on('console', m => msgs.push(`[${m.type()}] ${m.text()}`));
p.on('pageerror', e => msgs.push(`[pageerror] ${e.message}`));
await p.goto(url, { waitUntil: 'networkidle', timeout: 60000 }).catch(e => msgs.push('goto: '+e.message));
await p.waitForTimeout(wait);
const logText = await p.$eval('#log', el => el.textContent).catch(() => '(no #log)');
await p.screenshot({ path: out });
console.log('--- page log ---\n' + logText);
if (msgs.length) console.log('--- console ---\n' + msgs.slice(0,25).join('\n'));
await b.close();
