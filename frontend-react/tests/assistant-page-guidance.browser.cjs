const { chromium } = require('playwright')
const assert = require('node:assert/strict')

async function main() {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  try {
    const page = await browser.newPage()
    const html = `<!doctype html><html><body><div id="root"></div><script type="module">
      import RefreshRuntime from '/@react-refresh';
      RefreshRuntime.injectIntoGlobalHook(window); window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => (type) => type; window.__vite_plugin_react_preamble_installed__ = true;
    </script></body></html>`
    await page.route('**/__assistant_page_test', route => route.fulfill({ contentType: 'text/html', body: html }))
    await page.goto('http://127.0.0.1:5176/__assistant_page_test')

    const result = await page.evaluate(async () => {
      const [{ routeTeacherMessage }, { pageGuidanceText }, { clarify }] = await Promise.all([
        import('/src/assistant/orchestrate.ts'),
        import('/src/assistant/page-guidance.ts'),
        import('/src/assistant/clarify.ts'),
      ])
      const paths = [
        '/dashboard', '/onboarding', '/settings', '/staff', '/staff-positions', '/rbac',
        '/campus-buildings', '/students', '/classes', '/subjects', '/teacher-profiles',
        '/scheduling', '/gaokao', '/seating', '/exams', '/scans', '/exam-rooms',
        '/exam-venues', '/exam-calendar', '/exam-invigilators', '/exam-scheduling',
        '/grading/1', '/stats/1', '/meetings', '/file-center', '/ai-providers',
      ]
      return {
        campusNext: routeTeacherMessage('我下一步该干什么', '/campus-buildings'),
        studentHelp: routeTeacherMessage('这个页面怎么用', '/students'),
        systemHelp: routeTeacherMessage('系统怎么用', '/dashboard'),
        spaceClarify: clarify('空间资源怎么配置'),
        missingGuides: paths.filter((path) => !pageGuidanceText(path)),
      }
    })

    assert.deepEqual(result.campusNext, { kind: 'tool', tool: 'nextStep', path: '' })
    assert.deepEqual(result.studentHelp, { kind: 'tool', tool: 'pageGuide', path: '' })
    assert.deepEqual(result.systemHelp, { kind: 'tool', tool: 'howToUse', path: '/onboarding' })
    assert.equal(result.spaceClarify, null)
    assert.deepEqual(result.missingGuides, [])
    console.log('PASS: page-aware assistant routing and guidance cover all teacher menus')
  } finally {
    await browser.close()
  }
}

main().catch(error => { console.error(error); process.exitCode = 1 })
