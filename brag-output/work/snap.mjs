import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
const [,, mode, ...rest] = process.argv;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto('file://' + process.cwd() + '/comp/index.html');
await page.evaluate(() => window.ready);
if (mode === 'stills') {
  for (const t of rest) {
    await page.evaluate((t) => window.render(t), parseFloat(t));
    await page.screenshot({ path: `stills/t${t}.png` });
  }
} else {
  const fps = 30, dur = parseFloat(rest[0] || '22');
  for (let f = 0; f < Math.round(dur * fps); f++) {
    await page.evaluate((t) => window.render(t), f / fps);
    await page.screenshot({ path: `frames/${String(f).padStart(4, '0')}.jpg`, type: 'jpeg', quality: 94 });
  }
}
await browser.close();
