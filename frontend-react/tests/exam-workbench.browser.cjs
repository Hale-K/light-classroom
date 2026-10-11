const { chromium } = require('playwright')
const assert = require('node:assert/strict')
const path = require('node:path')
const fs = require('node:fs')

async function main() {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' })
  const output = path.resolve(__dirname, '../../output/exam-workbench')
  fs.mkdirSync(output, { recursive: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    page.setDefaultTimeout(10000)
    const errors = []; page.on('pageerror', e => errors.push(e.message))
    await page.addInitScript(() => { window.print = () => {} })
    const rooms = [{ id: 11, exam_schedule_id: 1, invigilator_ids: [1], invigilator_names: ['王老师'], grade_id: 1, grade_name: '高一', subject_id: 1, subject_name: '数学', exam_date: '2026-10-12', session_index: 1, start_time: '09:00', end_time: '11:00', room_name: 'A', capacity: 40, candidate_count: 2 }]
    const candidates = [{ id: 1, student_id: 1, exam_schedule_id: 1, exam_room_assignment_id: 11, grade_id: 1, subject_id: 1, student_name: '张同学', student_no: '2026001', grade_name: '高一', subject_name: '数学', exam_date: '2026-10-12', session_index: 1, start_time: '09:00', end_time: '11:00', room_name: 'A', seat_no: 1 }, { id: 2, student_id: 2, exam_schedule_id: 1, exam_room_assignment_id: 11, student_name: '李同学', seat_no: 2 }]
    candidates[1] = { ...candidates[0], ...candidates[1], student_no: '2026002' }
    const config = { exam_id: 2, grade_ids: [1], start_date: '2026-10-12', excluded_dates: [], sessions: [{ start_time: '09:00', end_time: '11:00' }], invigilators_per_room: 1 }
    const staff = [{ teacher_id: 1, teacher_name: '王老师', enabled: true, account_status: 'active', unavailable_slots: [], assigned_count: 1 }, { teacher_id: 2, teacher_name: '李老师', enabled: true, account_status: 'active', unavailable_slots: [], assigned_count: 0 }]
    let generated = false, preflightFail = true, seatChanges = 0, ticketPages = [], candidateFilters = []
    let savedTeachers = null
    const plan = () => ({ mode: 'custom', schedules: generated ? rooms : [], rooms: generated ? rooms : [], summary: { day_count: generated ? 1 : 0, session_count: generated ? 1 : 0, room_count: generated ? 1 : 0, student_count: generated ? 2 : 0, candidate_assignment_count: generated ? 2 : 0, invigilator_count: generated ? 1 : 0 } })
    await page.route('**/api/v1/**', async route => {
      const req = route.request(), url = new URL(req.url()), p = url.pathname.replace('/api/v1', '')
      let data = {}, status = 200
      if (p === '/exams') data = [{ id: 1, name: '其他考试', status: 'preparing' }, { id: 2, name: '高一期中考试', status: 'preparing' }]
      else if (p === '/org/grades' || p.endsWith('/grades')) data = [{ id: 1, name: '高一' }]
      else if (p.endsWith('/config')) { if (req.method() === 'PUT') Object.assign(config, req.postDataJSON()); data = config }
      else if (p.endsWith('/subjects')) data = [{ id: 1, name: '数学', grade_ids: [1] }]
      else if (p === '/exam-scheduling/rooms') data = { items: [{ id: 1, name: 'A', capacity: 40, status: 'available' }, { id: 2, name: 'B', capacity: 30, status: 'maintenance' }, { id: 3, name: 'C', capacity: 50, status: 'available' }], pagination: { total_pages: 1 } }
      else if (p.endsWith('/venues')) data = { confirmed: true, rooms: [{ name: 'A', capacity: 40 }], summary: { room_count: 1, seat_count: 40 } }
      else if (p.endsWith('/invigilators')) data = staff
      else if (/invigilators\/\d+$/.test(p)) { savedTeachers = req.postDataJSON(); data = { teacher_id: 1 } }
      else if (p.endsWith('/preview')) data = rooms
      else if (p === '/exam-scheduling/plans/check') {
        if (preflightFail) { status = 422; data = null } else data = { ok: true, student_count: 2, room_count: 1, session_count: 1 }
      }
      else if (p === '/exam-scheduling/plans' && req.method() === 'POST') { generated = true; data = plan() }
      else if (p.endsWith('/checks')) data = { ok: true, issues: [] }
      else if (p.endsWith('/overview')) data = { schedules: generated ? rooms.map(r => ({ ...r, exam_id: 2, exam_name: '高一期中考试' })) : [], rooms: generated ? rooms.map(r => ({ ...r, exam_id: 2, exam_name: '高一期中考试' })) : [], venues: [{ name: 'A', capacity: 40 }], teachers: [{ id: 1, name: '王老师' }], rules: { student_daily_limit: 4, min_break_minutes: 0, teacher_daily_limit: 4, avoid_own_subject: false, same_subject_same_time: false } }
      else if (/\/plans\/\d+$/.test(p)) data = plan()
      else if (p.endsWith('/candidates')) { candidateFilters.push(url.search); data = { items: generated ? candidates : [], pagination: { page: 1, total: generated ? 2 : 0, total_pages: 1 } } }
      else if (p.endsWith('/rooms/11') && req.method() === 'PATCH') { const body = req.postDataJSON(); assert.equal(Object.hasOwn(body, 'room_name') && Object.hasOwn(body, 'invigilator_ids'), false, 'each adjustment owns only its resource'); status = 409; data = null }
      else if (p.endsWith('/candidates/1') && req.method() === 'PATCH') { const body = req.postDataJSON(); assert.equal(body.swap, true); assert.equal(body.seat_no, 2); seatChanges++; data = candidates[0] }
      else if (p.endsWith('/admission-tickets')) {
        const n = Number(url.searchParams.get('page') || 1), size = Number(url.searchParams.get('page_size') || 100)
        ticketPages.push(n)
        const total = 201
        data = { exam_name: '高一期中考试', school_name: '测试学校', revision: 'v1', pagination: { total, total_pages: Math.ceil(total / size) }, items: Array.from({ length: Math.min(size, total - (n - 1) * size) }, (_, i) => ({ student_id: (n - 1) * size + i + 1, student_name: i === 0 ? '张同学 <script>alert(1)</script>' : `考生${i}`, student_no: '2026001', candidate_no: `E000002${i}`, grade_name: '高一', class_name: '1班', sessions: [{ subject_name: '数学', exam_date: '2026-10-12', start_time: '09:00', end_time: '11:00', room_name: 'A', seat_no: i + 1 }] })) }
      }
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(status === 200 ? { code: 0, data } : { detail: status === 422 ? '可用监考教师不足，请调整可用场次' : '李老师同时承担另一场监考，请更换教师' }) })
    })
    await page.goto('http://127.0.0.1:5176/tests/exam-workbench-fixture.html?examId=2')
    await page.getByRole('tab', { name: '考试设置', exact: true }).click()
    assert.equal(await page.locator('.es-kpis:visible').count(), 0)
    await page.getByRole('button', { name: '开始准备', exact: true }).click()
    const setup = page.locator('.es-setup-modal')
    await setup.getByText('准备排考 · 高一期中考试', { exact: true }).waitFor()
    await setup.locator('.ant-select').filter({ has: page.getByRole('combobox', { name: '考场编排', exact: true }) }).click()
    await page.locator('.ant-select-dropdown:visible').getByText('高考模拟', { exact: true }).click()
    assert.equal(await setup.getByRole('spinbutton', { name: '每个考场的监考人数' }).inputValue(), '2')
    await setup.getByRole('button', { name: '保存日程，下一步' }).click()
    await setup.getByRole('button', { name: '纳入全部可用考场', exact: true }).click()
    await setup.getByText('统考范围：已纳入全部 2 间可用考场', { exact: true }).waitFor()
    await setup.getByRole('columnheader', { name: '考试座位', exact: true }).waitFor()
    await setup.getByText('本场可用 60 个考试座位，每间最多 30 人；维修或停用空间不纳入。', { exact: true }).waitFor()
    await setup.getByRole('tab', { name: /监考教师/ }).click()
    await setup.getByRole('button', { name: '设置', exact: true }).first().click()
    await page.getByText('王老师 · 可用时间', { exact: true }).waitFor()
    await page.getByRole('button', { name: /保\s*存$/, exact: true }).click()
    await setup.getByRole('button', { name: '检查安排，下一步' }).click()
    await setup.getByText('可用监考教师不足，请调整可用场次', { exact: true }).waitFor()
    assert.equal(generated, false, 'failed checks must preserve existing results')
    assert(savedTeachers)
    preflightFail = false
    await setup.getByRole('button', { name: '检查安排，下一步' }).click()
    await setup.getByText('配置检查通过，可以生成安排').waitFor()
    await setup.screenshot({ path: path.join(output, 'setup.png') })
    await setup.getByRole('button', { name: /生\s*成\s*安\s*排/, exact: true }).click()
    await page.getByRole('tab', { name: '考生座位', exact: true }).click()
    await page.getByRole('button', { name: '调座位', exact: true }).first().waitFor()
    const gradeFilter = page.locator('.es-filter-bar .ant-select').first()
    await gradeFilter.click()
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: '高一' }).click()
    await gradeFilter.hover(); await gradeFilter.locator('.ant-select-clear').click()
    await page.waitForTimeout(100)
    assert(candidateFilters.some(f => f.includes('grade_id=1')))
    assert(!candidateFilters.at(-1).includes('grade_id='), 'clearing a filter removes its API constraint')
    await page.getByRole('tab', { name: '考试设置', exact: true }).click()
    await page.getByRole('button', { name: '检查冲突', exact: true }).click()
    await page.getByText('检查通过，人员、考场和座位未发现冲突').waitFor()
    await page.getByRole('tab', { name: '考场安排', exact: true }).click()
    await page.getByRole('button', { name: '设置可用考场', exact: true }).click()
    await setup.getByText('可用考场 · 高一期中考试', { exact: true }).waitFor()
    assert.equal(await setup.getByRole('tab', { name: /监考教师/ }).count(), 0)
    await setup.getByRole('button', { name: '稍后继续', exact: true }).click()
    await page.getByRole('button', { name: /调\s*整$/, exact: true }).first().click()
    assert.equal(await page.locator('.ant-modal:visible').getByText('监考教师', { exact: true }).count(), 0)
    await page.getByRole('button', { name: '保存调整', exact: true }).click()
    await page.getByText('李老师同时承担另一场监考，请更换教师', { exact: true }).waitFor()
    await page.getByRole('button', { name: /取\s*消$/, exact: true }).click()
    await page.getByRole('tab', { name: '监考安排', exact: true }).click()
    await page.getByRole('button', { name: '设置监考教师', exact: true }).click()
    await setup.getByText('监考教师 · 高一期中考试', { exact: true }).waitFor()
    assert.equal(await setup.getByRole('tab', { name: /考场 ·/ }).count(), 0)
    await setup.getByRole('button', { name: '完成设置', exact: true }).click()
    await page.locator('.ant-table-row-expand-icon').first().click()
    await page.getByRole('button', { name: '调整监考', exact: true }).first().click()
    await page.getByRole('dialog').getByText('调整监考 · A · 数学', { exact: true }).waitFor()
    assert.equal(await page.getByRole('dialog').getByRole('combobox', { name: '调整考场', exact: true }).count(), 0)
    await page.getByRole('button', { name: '保存调整', exact: true }).click()
    await page.getByText('李老师同时承担另一场监考，请更换教师', { exact: true }).waitFor()
    await page.getByRole('button', { name: /取\s*消$/, exact: true }).click()
    await page.getByRole('tab', { name: '考生座位', exact: true }).click()
    await page.getByRole('button', { name: '调座位', exact: true }).first().click()
    await page.getByRole('spinbutton', { name: '座位号' }).fill('2')
    await page.getByText('该座位是 李同学 的座位').waitFor()
    assert(await page.getByRole('button', { name: '保存调整', exact: true }).isDisabled())
    await page.getByRole('switch').click()
    await page.getByRole('button', { name: '保存调整', exact: true }).click()
    await page.getByRole('tab', { name: '打印材料', exact: true }).click()
    await page.getByRole('button', { name: '准考证打印' }).click()
    await page.getByRole('button', { name: '打印全部 201 张' }).waitFor()
    assert(ticketPages.includes(2), 'batch includes candidates beyond the first page')
    await page.locator('.es-tickets-modal').screenshot({ path: path.join(output, 'tickets.png') })
    assert.equal(await page.locator('.es-ticket-preview script').count(), 0, 'names are escaped')
    await page.getByRole('button', { name: '打印全部 201 张' }).click()
    await page.waitForTimeout(500)
    assert.equal(await page.locator('iframe').count(), 1)
    assert.equal(await page.frameLocator('iframe').locator('.exam-print-sheet').count(), 201)
    assert.equal(await page.frameLocator('iframe').locator('button').count(), 0)
    await page.getByRole('button', { name: /关\s*闭$/, exact: true }).click()
    await page.getByRole('tab', { name: '数据总览', exact: true }).click()
    assert.equal(await page.locator('.es-kpis:visible').count(), 1)
    await page.locator('.es-page').scrollIntoViewIfNeeded(); await page.evaluate(() => window.scrollTo(0, 0))
    await page.waitForTimeout(300)
    await page.screenshot({ path: path.join(output, 'desktop.png') })
    await page.setViewportSize({ width: 390, height: 844 })
    await page.screenshot({ path: path.join(output, 'mobile.png') })
    assert(await page.locator('.es-page').evaluate(e => e.scrollWidth <= e.clientWidth + 1), 'no page-level horizontal overflow')
    assert.equal(seatChanges, 1)
    assert.deepEqual(errors, [])
    console.log('PASS: guided setup, conflict recovery, explicit swap, complete batch print, escaped names, responsive layout; zero runtime errors')
  } catch (e) { await browser.contexts()[0]?.pages()[0]?.screenshot({ path: path.join(output, 'failure.png') }); throw e }
  finally { await browser.close() }
}
main().catch(e => { console.error(e); process.exitCode = 1 })
