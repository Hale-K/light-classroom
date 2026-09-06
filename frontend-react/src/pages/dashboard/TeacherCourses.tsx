import { Alert, Button, Empty, Spin } from 'antd'
import dayjs from 'dayjs'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { teacherProfilesApi } from '@/api'
import Icon from '@/components/Icon'
import { selectDisplayName, useAuthStore } from '@/store/auth'
import type { TeacherScheduleEntry } from '@/types'
import './teacher-courses.css'

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function currentTerm() {
  const now = dayjs()
  return {
    academicYear: now.month() >= 7 ? `${now.year()}-${now.year() + 1}` : `${now.year() - 1}-${now.year()}`,
    term: now.month() >= 1 && now.month() < 7 ? '2' : '1',
  }
}

export default function TeacherCourses() {
  const navigate = useNavigate()
  const teacherId = useAuthStore((state) => state.user?.id)
  const displayName = useAuthStore(selectDisplayName)
  const [{ academicYear, term }] = useState(currentTerm)
  const [items, setItems] = useState<TeacherScheduleEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const load = async () => {
    if (!teacherId) return
    setLoading(true)
    setError(false)
    try {
      const result = await teacherProfilesApi.weeklySchedule(teacherId, { academic_year: academicYear, term })
      setItems(result.items || [])
    } catch {
      setItems([])
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [teacherId, academicYear, term])

  const lessonsByDay = useMemo(() => WEEKDAYS.map((_, index) =>
    items.filter((item) => item.weekday === index + 1).sort((a, b) => a.period - b.period),
  ), [items])
  const classCount = new Set(items.map((item) => item.class_id)).size
  const subjectCount = new Set(items.map((item) => item.subject_id)).size

  return (
    <div className="teacher-courses-page">
      <header className="tc-page-head">
        <div>
          <span className="tc-eyebrow">MY COURSES / 我的课程</span>
          <h1>{displayName || '老师'}的课程</h1>
          <p>查看本人本学期的任教课程和每周课表。</p>
        </div>
        <div className="tc-term"><Icon name="calendar" size={16} />{academicYear} 学年 · 第 {term} 学期</div>
      </header>

      <section className="tc-summary" aria-label="课程概览">
        <div><span>每周课程</span><strong>{items.length}</strong><small>节</small></div>
        <div><span>任教班级</span><strong>{classCount}</strong><small>个</small></div>
        <div><span>任教学科</span><strong>{subjectCount}</strong><small>门</small></div>
        <Button type="primary" icon={<Icon name="edit" size={16} />} onClick={() => navigate('/teacher-preparation')}>进入备课</Button>
      </section>

      {error && <Alert type="error" showIcon message="课程加载失败" description="暂时无法读取个人课表，请稍后重试。" action={<Button onClick={() => void load()}>重新加载</Button>} />}
      <Spin spinning={loading} tip="正在加载课程">
        <section className="tc-week" aria-label="每周课程表">
          {lessonsByDay.map((lessons, dayIndex) => (
            <article className="tc-day" key={WEEKDAYS[dayIndex]}>
              <div className="tc-day-head"><h2>{WEEKDAYS[dayIndex]}</h2><span>{lessons.length} 节</span></div>
              {lessons.length ? lessons.map((lesson) => (
                <div className="tc-lesson" key={lesson.id}>
                  <span className="tc-period">第 {lesson.period} 节</span>
                  <strong>{lesson.subject_name || '课程'}</strong>
                  <span>{lesson.class_name || `班级 ${lesson.class_id}`}</span>
                  <small><Icon name="building" size={13} />{lesson.room || '常规教室'}</small>
                </div>
              )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无课程" />}
            </article>
          ))}
        </section>
      </Spin>
    </div>
  )
}
