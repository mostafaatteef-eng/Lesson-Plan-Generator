// Drives the built frontend in headless Chrome for i18n + failure-handling tests.
// Usage: node drive-ui-tests.mjs <scenario>
//   i18n   — screenshots AR desktop/mobile + EN desktop
//   fail401 — upload with wrong passcode: expect passcode cleared + rejection message
//   fail503 — upload with server disabled: expect server detail surfaced
//   failnet — no mock server running: expect network failure surfaced
import puppeteer from 'puppeteer-core';

const scenario = process.argv[2];
const BASE = 'http://127.0.0.1:8903/Lesson-Plan-Generator/';
const results = [];

const browser = await puppeteer.launch({
  executablePath: '/usr/bin/google-chrome',
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu'],
});

async function newPage(w = 1280, h = 1750) {
  const page = await browser.newPage();
  await page.setViewport({ width: w, height: h });
  return page;
}

async function uploadCurriculum(page) {
  const input = await page.$('#upload-curriculum');
  await input.uploadFile('/tmp/e2e_unit.txt');
  await new Promise((r) => setTimeout(r, 1800));
}

if (scenario === 'i18n') {
  let page = await newPage();
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await new Promise((r) => setTimeout(r, 800));
  const dir = await page.evaluate(() => document.documentElement.dir);
  results.push(`default dir=${dir} (expect rtl)`);
  await page.screenshot({ path: '/tmp/fe_ar_desktop.png' });
  // switch to English
  await page.click('button[aria-label="Switch interface language"]');
  await new Promise((r) => setTimeout(r, 500));
  const dir2 = await page.evaluate(() => document.documentElement.dir);
  results.push(`after toggle dir=${dir2} (expect ltr)`);
  await page.screenshot({ path: '/tmp/fe_en_desktop.png' });
  await page.close();
  // mobile Arabic
  page = await newPage(390, 844);
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: '/tmp/fe_ar_mobile.png' });
  // tablet Arabic
  await page.setViewport({ width: 820, height: 1180 });
  await new Promise((r) => setTimeout(r, 400));
  await page.screenshot({ path: '/tmp/fe_ar_tablet.png' });
}

if (scenario === 'fail401') {
  const page = await newPage();
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.type('#app-passcode', 'wrong-passcode');
  await uploadCurriculum(page);
  const err = await page.$eval('#upload-curriculum', () => {
    const el = document.querySelector('[role="alert"]');
    return el ? el.textContent : '(no alert)';
  });
  const pc = await page.$eval('#app-passcode', (el) => el.value);
  results.push(`401 alert: ${err.slice(0, 90)}`);
  results.push(`passcode field after 401: "${pc}" (expect empty)`);
  await page.screenshot({ path: '/tmp/fe_fail_401.png' });
}

if (scenario === 'fail503') {
  const page = await newPage();
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.type('#app-passcode', 'anything');
  await uploadCurriculum(page);
  const err = await page.$eval('#upload-curriculum', () => {
    const el = document.querySelector('[role="alert"]');
    return el ? el.textContent : '(no alert)';
  });
  const pc = await page.$eval('#app-passcode', (el) => el.value);
  results.push(`503 alert: ${err.slice(0, 110)}`);
  results.push(`passcode field after 503: "${pc}" (expect KEPT, not cleared)`);
  await page.screenshot({ path: '/tmp/fe_fail_503.png' });
}

if (scenario === 'failnet') {
  const page = await newPage();
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.type('#app-passcode', 'anything');
  await uploadCurriculum(page);
  const err = await page.$eval('#upload-curriculum', () => {
    const el = document.querySelector('[role="alert"]');
    return el ? el.textContent : '(no alert)';
  });
  results.push(`network-down alert: ${err.slice(0, 110)}`);
  await page.screenshot({ path: '/tmp/fe_fail_net.png' });
}

console.log(results.join('\n'));
await browser.close();
