const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')

async function main() {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const output = path.resolve(__dirname, '../../output/rule-workbench')
  fs.mkdirSync(output, { recursive: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
    const errors = []
    page.on('pageerror', error => { errors.push(error.message); console.log('PAGE ERROR:', error.message) })
    const rule = (id, subject, period) => ({ id, title: '学科课位限制', code: 'subject_allowed_slots', enabled: true, priority: 'hard', schedule_scope: 'all',
      target: { type: 'subject', ids: [subject] }, weekdays: [5], periods: [period], period_scope: 'regular', week_parity: 'all', params: {} })
    let group = { id: 'grade-1-test', name: '高一下学期排课规则', grade_id: 1, academic_year: '2026-2027', term: '2', version: 1,
      rules: [rule('R01', 1, 7), rule('R02', 2, 3)] }
    let failSave = true
    let saveCount = 0
    let lastSaved
    const grid = { configured: true, days: 6, periods_per_day: 9, daily_periods: [9, 9, 9, 9, 9, 7, 0], enable_saturday: true,
      enable_evening: true, evening_start_period: 10, evening_daily_periods_odd: [1, 1, 1, 1, 1, 0, 0], evening_daily_periods_even: [1, 1, 1, 1, 1, 0, 0],
      evening_subject_ids: [], evening_subject_ids_odd: [], evening_subject_ids_even: [], first_week_parity: 'odd' }
    await page.route('**/api/v1/**', async route => {
      const request = route.request()
      const url = request.url()
      let data = {}
      if (url.includes('/rule-groups')) data = { catalog_version: 2, active_id: group.id, groups: [group] }
      else if (url.includes('/grid-config')) data = grid
      else if (url.includes('/rule-group/validate')) data = { valid: true, compiled: true, schedule_available: false, schedule_item_count: 0, results: [], unresolved: [], score: 0 }
      else if (url.endsWith('/rule-group') && request.method() === 'PUT') {
        saveCount++
        if (failSave) { await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ code: 1, message: '测试保存失败，修改已保留', data: null }) }); return }
        lastSaved = request.postDataJSON(); group = lastSaved; data = { group, compiler: [] }
      }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ code: 0, message: 'ok', data }) })
    })
    await page.goto('http://127.0.0.1:5176/tests/rule-workbench-fixture.html')
    await page.getByRole('button', { name: /编\s*辑/ }).click({ timeout: 10000 }).catch(async error => { console.log('BODY:', (await page.locator('body').innerText()).slice(0,2000)); await page.screenshot({path:path.join(output,'debug.png')}); throw error })
    const workbench = page.locator('.rule-group-workbench-modal')
    await workbench.locator('.rule-group-card').first().waitFor()
    assert.match(await workbench.locator('.rule-group-card').first().innerText(), /班会.*周五.*第7节/s)
    assert.match(await workbench.locator('.rule-group-card').nth(1).innerText(), /数学.*第3节/s)
    await page.screenshot({ path: path.join(output, 'desktop.png') })
    await workbench.getByLabel('搜索规则', { exact: true }).fill('数学')
    assert.equal(await workbench.locator('.rule-group-card').count(), 1)
    await workbench.getByLabel('搜索规则', { exact: true }).fill('')
    await workbench.locator('.rule-group-card').first().click()
    const nameInput = workbench.locator('.rule-group-form > label').filter({ hasText: '规则名称' }).locator('input')
    await nameInput.fill('班会只排周五')
    await workbench.getByLabel('生效周期', { exact: true }).first().click()
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText: /^单周$/}).click()
    await workbench.getByRole('button', { name: '保存规则', exact: true }).click()
    await workbench.getByRole('alert').getByText('测试保存失败，修改已保留').waitFor()
    assert.match(await workbench.locator('.rule-group-card').first().innerText(), /学科课位限制/)
    assert.equal(await nameInput.inputValue(), '班会只排周五')
    assert(await workbench.getByRole('button', { name: '保存规则', exact: true }).isEnabled())
    failSave = false
    await workbench.getByRole('button', { name: '保存规则', exact: true }).click()
    await workbench.locator('.rule-group-card').filter({ hasText: '班会只排周五' }).waitFor()
    assert.equal(lastSaved.rules[0].week_parity, 'odd')
    assert(await workbench.getByRole('button', { name: '保存规则', exact: true }).isDisabled())
    await page.reload()
    await page.getByRole('button', { name: /编\s*辑/ }).click()
    assert.match(await workbench.locator('.rule-group-card').first().innerText(), /单周/)
    assert.match(await workbench.locator('.rule-group-card').nth(1).innerText(), /数学.*第3节/s)
    await workbench.getByRole('button', { name: '新增规则', exact: true }).click()
    const library = page.locator('.rule-type-picker-modal')
    await library.getByText('你希望课表怎样安排？').waitFor()
    await library.locator('.ant-modal-content').screenshot({ path: path.join(output, 'library.png') })
    await library.getByLabel('搜索规则场景', { exact: true }).fill('教研')
    assert.equal(await library.locator('.rule-group-template-card').count(), 1)
    await library.locator('.rule-group-template-card').click()
    const scope = workbench.locator('.rule-group-form > label').filter({ hasText: '作用对象' }).locator('.ant-select')
    await scope.click()
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText: /^全局$/}).click()
    await workbench.getByLabel('生效节次', { exact: true }).first().click()
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText: /^第7节$/}).click()
    await page.keyboard.press('Escape')
    await workbench.getByRole('button', { name: '保存规则', exact: true }).click()
    await workbench.getByRole('alert').getByText(/全部禁排/).waitFor()
    assert.equal(saveCount, 2, 'a conflicting hard rule must not be written')
    await workbench.getByRole('button', { name: '撤销修改', exact: true }).click()
    await workbench.getByRole('button', { name: '检查全部规则', exact: true }).click()
    await workbench.locator('.is-check-ok').waitFor()
    await page.setViewportSize({ width: 1024, height: 800 })
    await workbench.locator('.rule-workbench-inline-check').waitFor({ state: 'visible' })
    await page.screenshot({ path: path.join(output, 'compact.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    assert(await workbench.evaluate(element => element.scrollWidth <= element.clientWidth + 1))
    await page.screenshot({ path: path.join(output, 'mobile.png') })
    await page.setViewportSize({ width: 1600, height: 1000 })
    await workbench.getByRole('button', { name: '新增规则', exact: true }).click()
    await library.getByLabel('搜索规则场景', { exact: true }).fill('活动课')
    assert.equal(await library.locator('.rule-group-template-card').count(), 1, 'both period strategies share a single library entrance')
    assert.match(await library.locator('.rule-group-template-card').innerText(), /学科上课时段/)
    await library.locator('.rule-group-template-card').click()
    assert.equal(await workbench.getByLabel('学科节次安排方式', {exact:true}).count(),0,'ordinary subject preferences need no extra mode')
    await workbench.locator('.rule-group-form > label').filter({hasText:'选择学科'}).locator('.ant-select').click()
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText:/^数学$/}).click()
    await page.keyboard.press('Escape')
    const preferredPeriods=workbench.getByLabel('生效节次',{exact:true}).first()
    while(await preferredPeriods.locator('.ant-select-selection-item-remove').count()) await preferredPeriods.locator('.ant-select-selection-item-remove').first().click()
    await preferredPeriods.click()
    for(const period of [8,9]) await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({hasText:new RegExp(`^第${period}节$`)}).click()
    await page.keyboard.press('Escape')
    await workbench.getByRole('button',{name:'保存规则',exact:true}).click()
    await workbench.locator('.is-check-ok').waitFor()
    const preference=lastSaved.rules.find(r=>r.code==='subject_prefer_early_periods')
    assert.deepEqual(preference.target.ids,[2])
    assert.deepEqual(preference.periods,[8,9])
    assert.equal(preference.params.max_outside,2)
    assert.equal(preference.priority,'soft')
    await page.screenshot({path:path.join(output,'period-strategy.png')})
    await workbench.getByRole('button',{name:'必须满足',exact:true}).click()
    await workbench.getByRole('button',{name:'保存规则',exact:true}).click()
    await workbench.locator('.is-check-ok').waitFor()
    const restricted=lastSaved.rules.find(r=>r.code==='subject_allowed_slots')
    assert.deepEqual(restricted.target.ids,[2])
    assert.deepEqual(restricted.periods,[8,9])
    assert.equal(restricted.priority,'hard')

    group={...group,rules:[rule('R01',2,3),{...rule('R02',2,3),title:'王老师周五第3节禁排',code:'teacher_forbidden_slots',target:{type:'teacher',ids:[11]}}]}
    await page.reload()
    await page.getByRole('button',{name:/编\s*辑/}).click()
    const report=workbench.locator('.rule-group-audit .rule-workbench-report')
    assert.match(await report.innerText(),/高一（1）班.*数学.*王老师/s)
    await report.getByText('可以这样化解',{exact:true}).first().waitFor()
    await workbench.getByRole('button',{name:'检查全部规则',exact:true}).click()
    await workbench.locator('.is-check-error').getByText(/结构可解析，但仍有/).waitFor()
    await report.getByRole('button',{name:/调整 R02/}).first().click()
    assert.equal(await nameInput.inputValue(),'王老师周五第3节禁排')
    assert.match(await workbench.locator('.rule-group-card.is-selected').innerText(),/R02/)
    await page.screenshot({path:path.join(output,'conflict-remedies.png')})

    const load={...rule('R03-load',2,3),title:'王老师每日上限',code:'teacher_daily_limit',target:{type:'teacher',ids:[11]},weekdays:[1,2,3,4,5],periods:[],params:{max_lessons_per_day:3}}
    group={...group,rules:[load,{...load,id:'R03-continuity',code:'teacher_gap_free',params:{}}]}
    await page.reload()
    await page.getByRole('button',{name:/编\s*辑/}).click()
    const continuous=workbench.getByRole('checkbox',{name:'同时要求白天第 1～7 节中间不空节',exact:true})
    assert(await continuous.isChecked(),'existing bundled continuity is retained')
    await continuous.uncheck()
    await workbench.getByRole('button',{name:'保存规则',exact:true}).click()
    await workbench.locator('.is-check-ok').waitFor()
    assert.equal(lastSaved.rules.length,1)
    assert.equal(lastSaved.rules[0].code,'teacher_daily_limit')
    await page.reload()
    await page.getByRole('button',{name:/编\s*辑/}).click()
    assert(!await continuous.isChecked(),'load-only saved rule must not silently re-enable continuity')
    assert.deepEqual(errors, [])
    console.log('PASS: summaries, save recovery, parity, shared object and period fields, cross-assignment conflict explanations/navigation, explicit optional continuity and responsive layout')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
