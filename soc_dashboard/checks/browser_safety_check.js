// Safety proof for the generated pages. Needs Node with Playwright; axe-core is optional.
//
//   python3 checks/make_hostile_project.py /tmp/hostile
//   node checks/browser_safety_check.js site /tmp/hostile/site
//
// Checks, for every page in both sites:
//   1. no requests leave the machine except Google Fonts (no tracking, no data sent anywhere)
//   2. pages run under a strict Content-Security-Policy with no violations
//   3. hostile names from CSV files show as text and never run (window.__pwned stays unset)
//   4. the quick-search palette opens with Ctrl+K, finds things, navigates, and closes with Esc
//   5. no WCAG 2.1 AA violations from axe-core with the palette open (if axe-core is installed)
// Exits 1 if any check fails.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ALLOWED_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];
const CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; " +
  "font-src https://fonts.gstatic.com; img-src data:; connect-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'";
let axePath = null;
try { axePath = require.resolve('axe-core/axe.min.js'); } catch (e) { /* optional */ }

const failures = [];
function check(ok, what) { console.log((ok ? 'PASS ' : 'FAIL ') + what); if (!ok) failures.push(what); }

async function openPage(browser, dir, file) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const offsite = [], cspViolations = [];
  // Serve the built files from a fake origin so the CSP header applies, and record every request.
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === 'dash.local') {
      const local = path.join(dir, decodeURIComponent(url.pathname));
      if (!fs.existsSync(local)) return route.fulfill({ status: 404, body: '' });
      return route.fulfill({ status: 200, body: fs.readFileSync(local), headers: { 'content-type': 'text/html; charset=utf-8', 'content-security-policy': CSP } });
    }
    if (!ALLOWED_HOSTS.includes(url.hostname)) offsite.push(url.href);
    return route.abort();  // fonts too: the page must work without them
  });
  await page.exposeFunction('__cspViolation', (v) => cspViolations.push(v));
  await page.addInitScript(() => document.addEventListener('securitypolicyviolation', (e) => window.__cspViolation(e.violatedDirective + ' ' + e.blockedURI)));
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://dash.local/' + file);
  await page.waitForTimeout(300);
  return { page, offsite, cspViolations, errors };
}

(async () => {
  const [sampleDir, hostileDir] = process.argv.slice(2).map((d) => path.resolve(d));
  if (!sampleDir || !hostileDir) { console.error('usage: node browser_safety_check.js SAMPLE_SITE HOSTILE_SITE'); process.exit(2); }
  const browser = await chromium.launch();

  for (const dir of [sampleDir, hostileDir]) {
    const pages = fs.readdirSync(dir).filter((f) => f.endsWith('.html'));
    for (const f of pages) {
      const { page, offsite, cspViolations, errors } = await openPage(browser, dir, f);
      const label = path.basename(path.dirname(dir)) + '/' + f;
      check(offsite.length === 0, `${label}: no requests outside Google Fonts${offsite.length ? ' (' + offsite.join(', ') + ')' : ''}`);
      check(cspViolations.length === 0, `${label}: strict CSP, no violations${cspViolations.length ? ' (' + cspViolations.join('; ') + ')' : ''}`);
      check(errors.length === 0, `${label}: no script errors${errors.length ? ' (' + errors.join('; ') + ')' : ''}`);
      if (dir === hostileDir) {
        const r = await page.evaluate(() => ({ pwned: window.__pwned, img: document.querySelectorAll('img[src="x"]').length, svg: document.querySelectorAll('svg[onload]').length }));
        check(r.pwned === undefined && r.img === 0 && r.svg === 0, `${label}: injected names stay text (pwned=${r.pwned}, img=${r.img}, svg=${r.svg})`);
      }
      await page.close();
    }
  }

  // Palette behaviour on the hostile regression page: the hardest case.
  const reg = fs.readdirSync(hostileDir).find((f) => f.endsWith('-regression.html'));
  const { page } = await openPage(browser, hostileDir, reg);
  await page.keyboard.press('Control+k');
  check(await page.evaluate(() => document.getElementById('palette').open), 'palette: Ctrl+K opens it');
  await page.keyboard.type('img src');
  const labels = await page.$$eval('#pal-list .pal-label', (els) => els.map((e) => e.textContent));
  check(labels.includes('<img src=x onerror="window.__pwned=1">'), 'palette: a hostile test name is found and shown as plain text');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(200);
  const after = await page.evaluate(() => ({ pwned: window.__pwned, open: document.getElementById('palette').open, q: document.getElementById('search').value }));
  check(after.pwned === undefined && !after.open && after.q.startsWith('<img'), 'palette: choosing it filters the tests and nothing runs');

  await page.keyboard.press('Control+k');
  await page.keyboard.type('u_ddr1');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(200);
  check((await page.evaluate(() => location.hash)) === '#memory-ss--ddr-ctrl--u-ddr1', 'palette: Enter on an instance selects it in the tree');

  await page.click('#pal-open');
  await page.keyboard.type('zzzz-nothing');
  check((await page.$$('#pal-list [role=option]')).length === 0, 'palette: no match shows an empty-state message');
  if (axePath) {
    // Let time-based animations (the dialog's 180ms fade-in) finish so contrast is measured on
    // what people actually read; scroll-driven animations never finish, so skip those.
    await page.evaluate(() => Promise.all(document.getAnimations()
      .filter((a) => a.timeline instanceof DocumentTimeline).map((a) => a.finished.catch(() => null))));
    await page.addScriptTag({ path: axePath });
    const v = await page.evaluate(async () => (await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } })).violations.map((x) => x.id));
    check(v.length === 0, 'palette open: no WCAG 2.1 AA violations' + (v.length ? ' (' + v.join(', ') + ')' : ''));
  } else {
    console.log('SKIP axe-core not installed; accessibility scan not run');
  }
  await page.keyboard.press('Escape');
  const focus = await page.evaluate(() => ({ open: document.getElementById('palette').open, id: document.activeElement && document.activeElement.id }));
  check(!focus.open && focus.id === 'pal-open', 'palette: Esc closes it and returns focus to the Search button');

  await browser.close();
  console.log(failures.length ? `\n${failures.length} check(s) failed` : '\nAll safety checks passed');
  process.exit(failures.length ? 1 : 0);
})();
