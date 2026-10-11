const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

async function main() {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const output = path.resolve(__dirname, '../../output/student-choice')
  fs.mkdirSync(output, { recursive: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => localStorage.setItem('zh_student_token', 'ui-test-token'))
    const fixture = {
      scheme: { id: 1, name: '2026届 3+1+2 选科方案', mode: '3+1+2', required_subject_ids: [], primary_subject_ids: [1, 2], secondary_subject_ids: [3, 4, 5, 6] },
      subjects: [{ id: 1, name: '物理' }, { id: 2, name: '历史' }, { id: 3, name: '化学' }, { id: 4, name: '生物' }, { id: 5, name: '政治' }, { id: 6, name: '地理' }],
      choice: null, allow_teacher_pick: true, teachers_by_subject: {},
      teaching_classes: [
        { id: 11, subject_id: 3, name: '化学教学班 01', teacher_id: 9, teacher_name: '王老师', capacity: 40, selected_count: 32, remaining: 8, is_full: false, selected_by_me: false },
        { id: 12, subject_id: 3, name: '化学教学班 02', teacher_id: 10, teacher_name: '李老师', capacity: 40, selected_count: 40, remaining: 0, is_full: true, selected_by_me: false },
      ],
    }
    let payload
    await page.route('**/api/v1/**', async route => {
      const request = route.request()
      let data = {}
      if (request.url().includes('/student-auth/context')) data = { academic_year: '2026-2027', term: '2' }
      else if (request.url().includes('/student-auth/choice/options')) data = fixture
      else if (request.url().endsWith('/student-auth/choice') && request.method() === 'PUT') {
        payload = request.postDataJSON(); fixture.choice = { ...payload }; data = fixture.choice
      }
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ code: 0, message: 'ok', data }) })
    })
    await page.goto('http://127.0.0.1:5176/student/choice')
    await page.getByRole('heading', { name: '选择适合你的学科' }).waitFor()
    assert(await page.getByRole('button', { name: '核对并提交' }).isDisabled())
    await page.getByRole('button', { name: '物理，首选科目' }).click()
    await page.getByRole('button', { name: '化学，再选科目' }).click()
    await page.getByRole('button', { name: '地理，再选科目' }).click()
    assert(await page.getByRole('button', { name: '生物，再选科目' }).isDisabled())
    assert(await page.getByRole('button', { name: '核对并提交' }).isEnabled())
    await page.getByRole('button', { name: /选科目 \+ 选老师/ }).click()
    assert(await page.getByRole('button', { name: /李老师，化学教学班 02/ }).isDisabled())
    await page.getByRole('button', { name: /王老师，化学教学班 01/ }).click()
    await page.getByRole('button', { name: '刷新名额' }).click()
    await page.getByText('班级名额已更新', { exact: true }).waitFor()
    assert.equal(await page.getByRole('button', { name: /王老师，化学教学班 01/ }).getAttribute('aria-pressed'), 'true')
    assert.equal(await page.getByRole('button', { name: '物理，首选科目' }).getAttribute('aria-pressed'), 'true')
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: path.join(output, 'desktop-edit.png'), fullPage: true })
    await page.getByRole('button', { name: '核对并提交' }).click()
    await page.getByRole('button', { name: '确认提交', exact: true }).click()
    await page.getByText('等待班主任审核', { exact: true }).waitFor()
    assert.deepEqual(payload.teaching_class_preferences, { '3': 11 })
    assert.deepEqual(payload.secondary_subject_ids, [3, 6])
    fixture.choice.status = 'locked'
    await page.reload()
    await page.getByRole('heading', { name: '你的选科已确认' }).waitFor()
    assert.equal(await page.getByRole('button', { name: '核对并提交' }).count(), 0)
    await page.getByText('王老师 · 化学教学班 01', { exact: true }).waitFor()
    await page.screenshot({ path: path.join(output, 'desktop-locked.png'), fullPage: true })
    await page.screenshot({ path: path.join(output, 'desktop-overview.png') })
    fixture.choice = null; fixture.allow_teacher_pick = false
    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await page.getByRole('heading', { name: '选择适合你的学科' }).waitFor()
    assert(await page.getByRole('button', { name: /选科目 \+ 选老师/ }).isDisabled())
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true })
    assert.deepEqual(errors, [])
    console.log('PASS: subject limits, teacher gate, full class, refresh preservation, submit payload, locked result and mobile layout')
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
