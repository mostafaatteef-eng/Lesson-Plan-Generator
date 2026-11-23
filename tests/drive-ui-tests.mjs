// Drives the built frontend in headless Chrome for i18n + failure-handling tests.
// Usage: node drive-ui-tests.mjs <scenario>
//   i18n   — screenshots AR desktop/mobile + EN desktop
//   fail401 — upload with wrong passcode: expect passcode cleared + rejection message
//   fail503 — upload with server disabled: expect server detail surfaced
//   failnet — no mock server running: expect network failure surfaced
//   qafail — ambiguous lesson boundary: expect blocking-gate 422 banner, no downloads
import puppeteer from 'puppeteer-core';

const scenario = process.argv[2];
const BASE = process.env.BASE || 'http://127.0.0.1:8903/Lesson-Plan-Generator/';
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

if (scenario === 'fields') {
  // Teacher identity fields + template upload + generate -> QA-blocked state.
  const page = await newPage();
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.type('#app-passcode', 'test-pass');
  await uploadCurriculum(page);
  await new Promise((r) => setTimeout(r, 2500));
  const tpl = await page.$('#upload-template');
  await tpl.uploadFile('/tmp/ats_mu_official.docx');
  // Template parse runs a LibreOffice render server-side; allow it to finish.
  await new Promise((r) => setTimeout(r, 30000));
  // Select the first lesson checkbox.
  const lessonBoxes = await page.$$('input[type="checkbox"]');
  results.push(`lesson checkboxes found: ${lessonBoxes.length}`);
  const boxInfo = await page.$$eval('input[type="checkbox"]', (xs) =>
    xs.map((x) => ({ disabled: x.disabled, context: (x.closest('section') || x.parentElement).textContent.slice(0, 60) }))
  );
  results.push(`checkbox info: ${JSON.stringify(boxInfo)}`);
  // Select the first lesson via the select-all control (toggles all, then we
  // keep all selected: multi-lesson generate also exercises the batch path).
  const selectAllClicked = await page.$$eval('button', (bs) => {
    const b = bs.find((x) => x.textContent.includes('تحديد الكل'));
    if (b) { b.click(); return true; }
    return false;
  });
  results.push(`select-all clicked: ${selectAllClicked}`);
  await new Promise((r) => setTimeout(r, 500));
  const checkedCount = await page.$$eval('input[type="checkbox"]', (xs) => xs.filter((x) => x.checked).length);
  results.push(`checkboxes checked after click: ${checkedCount}`);
  const btnProbe = await page.$$eval('button', (bs) =>
    bs.filter((x) => x.className.includes('min-h-[50px]')).map((x) => ({ disabled: x.disabled, text: x.textContent.slice(0, 30) }))
  );
  results.push(`generate buttons: ${JSON.stringify(btnProbe)}`);
  // Open advanced settings and fill the teacher identity fields.
  await page.click('button[aria-expanded]');
  await new Promise((r) => setTimeout(r, 400));
  await page.type('#ebda-teacher-name', 'معلم اختبار');
  await page.type('#ebda-class-section', '٣/١');
  await page.type('#ebda-lesson-date', '١٤٤٧/٦/٥');
  await new Promise((r) => setTimeout(r, 300));
  await page.screenshot({ path: '/tmp/fe_teacher_fields.png' });
  // Generate: with the approved +1 page tolerance, this lesson now passes QA.
  // The honest outcome is a success state with working download buttons.
  const clicked = await page.$$eval('button', (bs) => {
    const b = bs.find((x) => x.className.includes('min-h-[50px]') && !x.disabled);
    if (b) { b.click(); return true; }
    return false;
  });
  results.push(`generate button clicked: ${clicked}`);
  await new Promise((r) => setTimeout(r, 120000));
  const state = await page.evaluate(() => {
    const txt = document.body.innerText;
    const dlButtons = [...document.querySelectorAll('button')].filter((b) =>
      b.textContent.includes('تنزيل') && !b.disabled
    );
    return {
      planReady: txt.includes('خطة الدرس جاهزة'),
      hasFailureBox: txt.includes('دروس تعذّر إنشاؤها'),
      downloadButtons: dlButtons.length,
      qaLabel: txt.includes('الجودة:'),
      alert: (document.querySelector('[role="alert"]') || {}).textContent || '(none)',
    };
  });
  results.push(`planReady: ${state.planReady} (expect true)`);
  results.push(`qa label: ${state.qaLabel} (expect true)`);
  results.push(`failures box: ${state.hasFailureBox} (expect false)`);
  results.push(`download buttons: ${state.downloadButtons} (expect >= 2)`);
  results.push(`alert: ${state.alert.slice(0, 100)}`);
  await page.screenshot({ path: '/tmp/fe_success.png', fullPage: true });
}

if (scenario === 'qafail') {
  // Intentional failure: a unit with no lesson headings produces an
  // unapproved, ambiguous lesson boundary, which is a blocking QA gate.
  // The honest outcome is a 422 error banner with the Arabic blocking
  // reason and NO generated plan or downloads.
  const page = await newPage();
  await page.goto(BASE, { waitUntil: 'networkidle0' });
  await page.type('#app-passcode', 'test-pass');
  const input = await page.$('#upload-curriculum');
  await input.uploadFile('/tmp/e2e_unit_noheadings.txt');
  await new Promise((r) => setTimeout(r, 2500));
  const tpl = await page.$('#upload-template');
  await tpl.uploadFile('/tmp/ats_mu_official.docx');
  await new Promise((r) => setTimeout(r, 30000));
  const clicked = await page.$$eval('button', (bs) => {
    const b = bs.find((x) => x.className.includes('min-h-[50px]') && !x.disabled);
    if (b) { b.click(); return true; }
    return false;
  });
  results.push(`generate button clicked: ${clicked}`);
  await new Promise((r) => setTimeout(r, 60000));
  const state = await page.evaluate(() => {
    const txt = document.body.innerText;
    return {
      planReady: txt.includes('خطة الدرس جاهزة'),
      alert: (document.querySelector('[role="alert"]') || {}).textContent || '(none)',
      downloadButtons: [...document.querySelectorAll('button')].filter((b) =>
        b.textContent.includes('تنزيل') && !b.disabled
      ).length,
    };
  });
  results.push(`planReady: ${state.planReady} (expect false)`);
  results.push(`download buttons: ${state.downloadButtons} (expect 0)`);
  results.push(`alert mentions blocked boundary: ${state.alert.includes('حدود الدرس') || state.alert.includes('فحوصات الجودة') || state.alert.includes('تعذّر')} (expect true)`);
  results.push(`alert: ${state.alert.slice(0, 140)}`);
  await page.screenshot({ path: '/tmp/fe_qa_fail.png', fullPage: true });
}

console.log(results.join('\n'));
await browser.close();
