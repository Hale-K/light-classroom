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
    await page.route('**/api/v1/facilities/overview', route => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ code: 0, message: 'ok', data: { stats: { campus_count: 1, building_count: 0, room_count: 0, multimedia_count: 0 }, campuses: [], buildings: [] } }),
    }))
    await page.route('**/api/v1/facilities/rooms', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify({ code: 0, message: 'ok', data: [] }),
    }))
    await page.route('**/api/v1/facilities/allocation-rules', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify({ code: 0, message: 'ok', data: [] }),
    }))
    await page.goto('http://127.0.0.1:5176/__assistant_page_test')

    const result = await page.evaluate(async () => {
      const [{ pageGuidanceText }, { runAssistantTool }, { decideJumpReply }] = await Promise.all([
        import('/src/assistant/page-guidance.ts'),
        import('/src/assistant/run.ts'),
        import('/src/assistant/jump-intent.ts'),
      ])
      const paths = [
        '/dashboard', '/onboarding', '/settings', '/staff', '/staff-positions', '/rbac',
        '/campus-buildings', '/students', '/classes', '/subjects', '/teacher-profiles',
        '/scheduling', '/gaokao', '/seating', '/exams', '/exam-rooms',
        '/exam-venues', '/exam-calendar', '/exam-invigilators', '/exam-scheduling',
        '/grading/1', '/stats/1', '/file-center', '/ai-providers',
      ]
      const progress = []
      const spaceNext = await runAssistantTool(
        'nextStep',
        '',
        { here: '/campus-buildings?tab=resources', traceId: 'browser-test' },
        line => progress.push(line),
      )
      return {
        missingGuides: paths.filter((path) => !pageGuidanceText(path)),
        spaceNext,
        progress,
        jumpYes: decideJumpReply('好的，帮我跳转', [{ label: '打开规则', path: '/campus-buildings?tab=allocation' }]),
        jumpNo: decideJumpReply('暂时不用', [{ label: '打开规则', path: '/campus-buildings?tab=allocation' }]),
        jumpUnclear: decideJumpReply('规则是什么意思', [{ label: '打开规则', path: '/campus-buildings?tab=allocation' }]),
      }
    })

    assert.deepEqual(result.missingGuides, [])
    assert.match(result.spaceNext.report, /选中已有校区/)
    assert.match(result.spaceNext.report, /0 栋楼宇/)
    assert.deepEqual(result.progress, ['读取空间资源现状', '判断阶段：1 个校区，0 栋楼宇，0 间场室'])
    assert.equal(result.jumpYes.kind, 'confirm')
    assert.equal(result.jumpNo.kind, 'cancel')
    assert.equal(result.jumpUnclear.kind, 'none')
    console.log('PASS: page guidance, explicit task action, and conversational jump confirmation')
  } finally {
    await browser.close()
  }
}

main().catch(error => { console.error(error); process.exitCode = 1 })
