import { useEffect, useMemo, useState } from 'react'
import { App, Button, DatePicker, Select, Spin, Tag } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { examApi, examSchedulingApi, orgApi } from '@/api'
import type { Exam, ExamScheduleEntry, Grade } from '@/types'
import PageHeader from '@/components/PageHeader'
import Icon from '@/components/Icon'
import ExamModuleNav from '@/pages/exam-scheduling/ModuleNav'
import '@/pages/exam-scheduling/index.css'

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
function timeOptions(start: string, end: string, step = 30) {
  const options: string[] = []; let [hour, minute] = start.split(':').map(Number); const [endHour, endMinute] = end.split(':').map(Number)
  while (hour * 60 + minute <= endHour * 60 + endMinute) { options.push(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`); minute += step; if (minute >= 60) { hour += 1; minute -= 60 } }
  return options.map((value) => ({ label: value, value }))
}

export default function ExamCalendarView() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [exams, setExams] = useState<Exam[]>([])
  const [grades, setGrades] = useState<Grade[]>([])
  const [gradeIds, setGradeIds] = useState<number[]>([])
  const [examId, setExamId] = useState<number>()
  const [schedule, setSchedule] = useState<ExamScheduleEntry[]>([])
  const [venuesReady, setVenuesReady] = useState(false)
  const [startDate, setStartDate] = useState(dayjs().format('YYYY-MM-DD'))
  const [excludedDates, setExcludedDates] = useState<string[]>([])
  const [morningStart, setMorningStart] = useState('09:00'), [morningEnd, setMorningEnd] = useState('11:00')
  const [afternoonStart, setAfternoonStart] = useState('14:30'), [afternoonEnd, setAfternoonEnd] = useState('16:30')
  const [invigilatorsPerRoom, setInvigilatorsPerRoom] = useState(1)

  const loadExam = async (id: number) => {
    setLoading(true)
    try { const [rows, venuePlan, config] = await Promise.all([examSchedulingApi.get(id), examSchedulingApi.venues(id), examSchedulingApi.config(id)]); setSchedule(rows); setVenuesReady(venuePlan.confirmed); setGradeIds(config.grade_ids); if (config.start_date) setStartDate(config.start_date); setExcludedDates(config.excluded_dates || []); if (config.sessions?.[0]) { setMorningStart(config.sessions[0].start_time); setMorningEnd(config.sessions[0].end_time) } if (config.sessions?.[1]) { setAfternoonStart(config.sessions[1].start_time); setAfternoonEnd(config.sessions[1].end_time) } setInvigilatorsPerRoom(config.invigilators_per_room || 1) }
    catch (error) { message.error(error instanceof Error ? error.message : '考试日程加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { Promise.all([examApi.list(), orgApi.grades()]).then(([rows, gradeRows]) => { setExams(rows); setGrades(gradeRows); if (rows[0]) { setExamId(rows[0].id); void loadExam(rows[0].id) } }) }, [])

  const grouped = useMemo(() => {
    const map = new Map<string, ExamScheduleEntry[]>(); schedule.forEach((item) => map.set(item.exam_date, [...(map.get(item.exam_date) || []), item])); return [...map.entries()]
  }, [schedule])
  const generate = async () => {
    if (!examId || !venuesReady) return message.warning('请先到“考场安排”确认本次考试考场')
    setLoading(true)
    try {
      const sessions = [{ start_time: morningStart, end_time: morningEnd }, { start_time: afternoonStart, end_time: afternoonEnd }]
      await examSchedulingApi.saveConfig(examId, { grade_ids: gradeIds, start_date: startDate, excluded_dates: excludedDates, sessions, invigilators_per_room: invigilatorsPerRoom })
      const plan = await examSchedulingApi.generatePlan({ exam_id: examId, grade_ids: gradeIds, start_date: startDate, room: '按已确认考场分配', excluded_dates: excludedDates, sessions, invigilators_per_room: invigilatorsPerRoom })
      setSchedule(plan.schedules); message.success(`已生成 ${plan.summary.day_count} 天考试日程`)
    } catch (error) { message.error(error instanceof Error ? error.message : '考试日程生成失败') }
    finally { setLoading(false) }
  }

  return <Spin spinning={loading}><div className="es-page">
    <PageHeader title="考试日程" extra={<><Button onClick={() => window.print()}>打印日期表</Button><Button type="primary" disabled={!venuesReady} onClick={generate}>生成考试日程</Button></>} />
    <p className="zh-page-desc">这里只设置考试日期和场次，生成后到“人员排考”查看考生、座位与监考安排。</p>
    <ExamModuleNav />
    <div className="es-layout">
      <aside className="es-config"><div className="es-panel-title"><h3>日程条件</h3><span>日期与考试场次</span></div>
        <label className="es-label">考试<Select value={examId} onChange={(id) => { setExamId(id); void loadExam(id) }} options={exams.map((exam) => ({ label: exam.name, value: exam.id }))} /></label>
        <label className="es-label">参考年级<Select mode="multiple" value={gradeIds} disabled options={grades.map((grade) => ({ label: grade.name, value: grade.id }))} /></label>
        <label className="es-label">开始日期<DatePicker value={dayjs(startDate)} onChange={(value: Dayjs | null) => setStartDate((value || dayjs()).format('YYYY-MM-DD'))} /></label>
        <label className="es-label">避考日期<DatePicker value={excludedDates.length ? excludedDates.map((date) => dayjs(date)) : null} onChange={(values) => setExcludedDates(values ? values.map((value) => value.format('YYYY-MM-DD')) : [])} multiple /></label>
        <div className="es-session"><span>场次设置</span><div><b>上午</b><Select value={morningStart} onChange={setMorningStart} options={timeOptions('07:00', '12:00')} /><i>至</i><Select value={morningEnd} onChange={setMorningEnd} options={timeOptions('08:00', '13:00')} /></div><div><b>下午</b><Select value={afternoonStart} onChange={setAfternoonStart} options={timeOptions('13:00', '17:00')} /><i>至</i><Select value={afternoonEnd} onChange={setAfternoonEnd} options={timeOptions('14:00', '19:00')} /></div></div>
        <label className="es-label">每考场监考人数<Select value={invigilatorsPerRoom} onChange={setInvigilatorsPerRoom} options={[1, 2, 3].map((value) => ({ label: `${value} 人`, value }))} /></label>
        <div className="es-rule-note"><strong>{venuesReady ? '考场已确认' : '尚未确认考场'}</strong><span>{venuesReady ? '可以生成考试日程。' : '请先完成考场安排。'}</span></div>
      </aside>
      <section className="es-surface"><div className="es-surface-head"><div><h3>考试日期表</h3><span>按天查看科目与场次</span></div><div className="es-summary"><div><strong>{grouped.length}</strong><span>考试日</span></div><div><strong>{schedule.length}</strong><span>科目场次</span></div></div></div>
        {grouped.length ? <div className="es-days">{grouped.map(([date, rows]) => { const value = dayjs(`${date}T00:00:00`); return <article className="es-day" key={date}><header><div className="es-date-block"><strong>{value.format('DD')}</strong><span>{value.month() + 1}月</span></div><div><b>{WEEKDAYS[value.day()]}</b><small>{date}</small></div><em>{rows.length} 场</em></header><div className="es-day-line">{rows.map((row) => <div className="es-card" key={row.id}><span className="es-time">{row.start_time}—{row.end_time}</span><div className="es-subject-row"><strong>{row.subject_name}</strong><Tag>{row.grade_name}</Tag></div></div>)}</div></article> })}</div> : <div className="es-empty"><Icon name="clipboard" size={32} /><strong>还没有考试日程</strong><span>设置左侧日期与场次后生成。</span></div>}
      </section>
    </div>
  </div></Spin>
}
