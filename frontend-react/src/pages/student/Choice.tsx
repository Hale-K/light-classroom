import { translate as t, useLocale } from '@/i18n'
import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Empty, Form, Modal, Select, Skeleton } from 'antd'
import { CheckOutlined, CheckCircleFilled, ClockCircleOutlined, LockOutlined, LogoutOutlined, ReadOutlined, ReloadOutlined, SaveOutlined, SendOutlined, TeamOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { studentAuthApi } from '@/api'
import type { StudentChoiceOptions } from '@/api'
import './student.css'
import './choice.css'

export default function StudentChoice() {
  const locale = useLocale()
  const { message } = App.useApp()
  const navigate = useNavigate()
  const [data, setData] = useState<StudentChoiceOptions>()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [form] = Form.useForm()
  const [academicYear, setAcademicYear] = useState<string>()
  const [term, setTerm] = useState<string>()
  const [selectionMode, setSelectionMode] = useState<'course' | 'teacher'>('course')
  const primarySubject = Form.useWatch('primary_subject_id', form) as number | undefined
  const secondarySubjects = Form.useWatch('secondary_subject_ids', form) as number[] | undefined
  const selectedSubjects = [primarySubject, ...(secondarySubjects || [])].filter((id): id is number => id !== undefined)
  const selectedClasses = Form.useWatch('teaching_class_preferences', form) as Record<string, number> | undefined

  const load = async () => {
    setLoading(true)
    setLoadError('')
    try {
      const context = await studentAuthApi.context()
      setAcademicYear(context.academic_year)
      setTerm(context.term)
      const result = await studentAuthApi.options({ academic_year: context.academic_year, term: context.term })
      setData(result)
      form.setFieldsValue({ primary_subject_id: result.choice?.primary_subject_id, secondary_subject_ids: result.choice?.secondary_subject_ids || [], teaching_class_preferences: result.choice?.teaching_class_preferences || {} })
      setSelectionMode(result.allow_teacher_pick && Object.keys(result.choice?.teaching_class_preferences || {}).length ? 'teacher' : 'course')
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : t("选科信息加载失败"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!localStorage.getItem('zh_student_token')) { navigate('/student/login', { replace: true }); return }
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const subjectMap = useMemo(() => new Map((data?.subjects || []).map((item) => [item.id, item.name])), [data, locale])
  const choice = data?.choice
  const locked = choice?.status === 'locked'
  const complete = primarySubject !== undefined && (secondarySubjects || []).length === 2
  const nameOf = (id: number) => subjectMap.get(id) || t("科目 {{p0}}", { p0: id })
  const selectedClass = (id: number) => data?.teaching_classes?.find((item) => item.id === selectedClasses?.[String(id)])
  const status = locked ? t("已审核通过") : choice?.status === 'confirmed' ? t("等待班主任审核") : choice?.status === 'rejected' ? t("已退回，请修改") : choice?.status === 'draft' ? t("草稿已保存") : t("尚未提交")
  const refreshSeats = async () => {
    if (!academicYear || !term) return
    setRefreshing(true)
    try {
      const result = await studentAuthApi.options({ academic_year: academicYear, term })
      setData(result)
      if (!result.allow_teacher_pick) setSelectionMode('course')
      if (result.choice?.status === 'locked') form.setFieldsValue({ primary_subject_id: result.choice.primary_subject_id, secondary_subject_ids: result.choice.secondary_subject_ids, teaching_class_preferences: result.choice.teaching_class_preferences || {} })
      message.success(t("班级名额已更新"))
    } catch (error) { message.error(error instanceof Error ? error.message : t("名额刷新失败")) }
    finally { setRefreshing(false) }
  }

  const submit = async (nextStatus: 'draft' | 'confirmed') => {
    if (!data?.scheme || !academicYear || !term || locked) return
    setSaving(true)
    try {
      const values = await form.validateFields()
      const classPreferences = data.allow_teacher_pick && selectionMode === 'teacher'
        ? Object.fromEntries(selectedSubjects.filter((id) => values.teaching_class_preferences?.[String(id)] != null).map((id) => [String(id), values.teaching_class_preferences[String(id)]])) : {}
      await studentAuthApi.saveChoice({ scheme_id: data.scheme.id, academic_year: academicYear, effective_term: term, primary_subject_id: values.primary_subject_id, secondary_subject_ids: values.secondary_subject_ids, teaching_class_preferences: classPreferences, status: nextStatus })
      setConfirmOpen(false)
      message.success(nextStatus === 'confirmed' ? t("已提交，等待班主任审核") : t("草稿已保存"))
      await load()
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("选科保存失败"))
    } finally {
      setSaving(false)
    }
  }

  const logout = () => {
    localStorage.removeItem('zh_student_token')
    localStorage.removeItem('zh_student_user')
    navigate('/student/login', { replace: true })
  }

  if (loading) return <main className="student-shell choice-shell"><div className="choice-page"><Skeleton active paragraph={{ rows: 9 }} /></div></main>
  if (loadError || !data?.scheme) return <main className="student-shell choice-shell"><div className="choice-page choice-empty">
    {loadError ? <Alert type="error" showIcon message={t("暂时无法加载选科信息")} description={loadError} action={<Button onClick={() => void load()}>{t("重试")}</Button>} /> : <Empty description={t("学校尚未配置选科方案")} />}
    <Button onClick={logout}>{t("返回登录")}</Button>
  </div></main>
  const scheme = data.scheme
  const chooseSubject = (id: number, primary: boolean) => {
    if (locked || saving) return
    if (primary) {
      if (primarySubject !== undefined && primarySubject !== id) form.setFieldValue(['teaching_class_preferences', String(primarySubject)], undefined)
      form.setFieldValue('primary_subject_id', id)
    } else {
      const current = secondarySubjects || []
      if (current.includes(id)) {
        form.setFieldValue('secondary_subject_ids', current.filter((item) => item !== id))
        form.setFieldValue(['teaching_class_preferences', String(id)], undefined)
      } else if (current.length < 2) form.setFieldValue('secondary_subject_ids', [...current, id])
    }
  }
  const subjectCards = (ids: number[], primary: boolean) => <div className={`choice-subject-grid ${primary ? 'primary-grid' : ''}`}>
    {ids.map((id) => {
      const selected = primary ? primarySubject === id : (secondarySubjects || []).includes(id)
      return <button type="button" key={id} aria-pressed={selected} aria-label={t("{{p0}}，{{p1}}科目", { p0: nameOf(id), p1: primary ? t("首选") : t("再选") })}
        className={`choice-subject ${selected ? 'is-selected' : ''} ${locked ? 'is-readonly' : ''}`}
        disabled={locked || saving || (!primary && (secondarySubjects || []).length >= 2 && !selected)} onClick={() => chooseSubject(id, primary)}>
        <span className="choice-subject-symbol" aria-hidden="true">{nameOf(id).slice(0, 1)}</span><span><strong>{nameOf(id)}</strong><small>{selected ? locked ? t("已确认") : primary ? t("已选为首选") : t("已选择 · 点击取消") : t("点击选择")}</small></span><i>{selected && <CheckOutlined />}</i>
      </button>
    })}
  </div>
  return <main className="student-shell choice-shell"><div className="choice-page">
    <header className="choice-topbar"><div className="choice-brand"><span><ReadOutlined /></span>{t("轻课堂")}<small>{t("学生选科")}</small></div>
      <Button type="text" icon={<LogoutOutlined />} onClick={logout}>{t("退出登录")}</Button></header>
    <div className="choice-heading"><div><span className="choice-overline">{t("{{p0}} 学年 · 第 {{p1}} 学期", { p0: academicYear, p1: term })}</span><h1>{locked ? t("你的选科已确认") : t("选择适合你的学科")}</h1>
      <p>{locked ? t("以下是已审核通过的选科结果。需要调整时，请联系班主任。") : t("先选 1 门首选科目，再选 2 门再选科目，组成你的学科组合。")}</p></div>
      <span className={`choice-status ${locked ? 'is-approved' : ''}`}>{locked ? <CheckCircleFilled /> : <ClockCircleOutlined />}{status}</span></div>
    <Form form={form} layout="vertical" disabled={locked || saving}>
      <Form.Item name="primary_subject_id" hidden rules={[{ required: true, message: t("请选择首选科目") }]}><Select /></Form.Item>
      <Form.Item name="secondary_subject_ids" hidden rules={[{ validator: (_, value: number[]) => value?.length === 2 ? Promise.resolve() : Promise.reject(new Error(t("请选择两门再选科目"))) }]}><Select mode="multiple" /></Form.Item>
      <div className="choice-layout"><div className="choice-main">
        {!locked && <section className="choice-panel choice-modes" aria-label={t("选择模式")}><div className="choice-section-heading"><div><h2>{t("你想怎么选？")}</h2><p>{t("科目自己选，老师也可以交给学校安排。")}</p></div></div>
          <div className="choice-mode-grid">
            <button type="button" aria-pressed={selectionMode === 'course'} className={`choice-mode ${selectionMode === 'course' ? 'is-selected' : ''}`} disabled={saving} onClick={() => setSelectionMode('course')}><ReadOutlined /><span><strong>{t("只选科目")}</strong><small>{t("老师和教学班由学校安排")}</small></span><i>{selectionMode === 'course' && <CheckOutlined />}</i></button>
            <button type="button" aria-pressed={selectionMode === 'teacher'} className={`choice-mode ${selectionMode === 'teacher' ? 'is-selected' : ''}`} disabled={saving || !data.allow_teacher_pick} onClick={() => setSelectionMode('teacher')}><TeamOutlined /><span><strong>{t("选科目 + 选老师")}</strong><small>{data.allow_teacher_pick ? t("查看老师开班，选择有余量的班") : t("教务暂未开放选老师")}</small></span><i>{selectionMode === 'teacher' && <CheckOutlined />}</i></button>
          </div></section>}
        <section className="choice-panel" aria-labelledby="choice-primary-title"><div className="choice-section-heading"><div className="choice-step-title"><span className="choice-step">01</span><div><h2 id="choice-primary-title">{t("首选科目")}</h2><p>{locked ? t("已确认的首选科目") : t("物理、历史中选择 1 门")}</p></div></div><span className="choice-count">{primarySubject === undefined ? 0 : 1} {t("/ 1 门")}</span></div>
          {subjectCards(locked && primarySubject !== undefined ? [primarySubject] : scheme.primary_subject_ids, true)}</section>
        <section className="choice-panel" aria-labelledby="choice-secondary-title"><div className="choice-section-heading"><div className="choice-step-title"><span className="choice-step">02</span><div><h2 id="choice-secondary-title">{t("再选科目")}</h2><p>{locked ? t("已确认的再选科目") : (secondarySubjects || []).length === 2 ? t("已选满 2 门，取消一门后可更换") : t("化学、生物、政治、地理中选择 2 门")}</p></div></div><span className="choice-count">{(secondarySubjects || []).length} {t("/ 2 门")}</span></div>
          {subjectCards(locked ? secondarySubjects || [] : scheme.secondary_subject_ids, false)}</section>
        {data.allow_teacher_pick && selectionMode === 'teacher' && <section className="choice-panel" aria-labelledby="choice-teachers-title"><div className="choice-section-heading"><div className="choice-step-title"><span className="choice-step">03</span><div><h2 id="choice-teachers-title">{locked ? t("已选老师与教学班") : t("选择老师的教学班")}</h2><p>{t("每科可选一个班，也可以交给学校安排。")}</p></div></div>
          {!locked && <Button type="text" icon={<ReloadOutlined />} loading={refreshing} disabled={saving} onClick={() => void refreshSeats()}>{t("刷新名额")}</Button>}</div>
          {!selectedSubjects.length && <div className="choice-inline-empty">{t("先选择科目，这里会展示对应老师的教学班。")}</div>}
          {selectedSubjects.map((id) => {
            const classes = (data.teaching_classes || []).filter((item) => item.subject_id === id)
            const chosen = selectedClass(id)
            return <div className="choice-teacher-group" key={id}><h3>{nameOf(id)}<span>{chosen ? t("已选 {{p0}}", { p0: chosen.teacher_name }) : t("由学校安排")}</span></h3>
              <Form.Item name={['teaching_class_preferences', String(id)]} hidden><Select /></Form.Item>
              {locked ? <div className="choice-locked-teacher">{chosen ? `${chosen.teacher_name} · ${chosen.name}` : t("教学班由教务安排")}</div> : <div className="choice-teacher-grid">
                <button type="button" aria-pressed={!selectedClasses?.[String(id)]} className={`choice-teacher choice-auto ${!selectedClasses?.[String(id)] ? 'is-selected' : ''}`} disabled={saving} onClick={() => form.setFieldValue(['teaching_class_preferences', String(id)], undefined)}><span className="choice-avatar"><TeamOutlined /></span><strong>{t("学校统一安排")}</strong><small>{t("由教务安排老师和教学班")}</small><span className="choice-teacher-action">{!selectedClasses?.[String(id)] ? <><CheckOutlined /> {t("已选择")}</> : t("选择统一安排")}</span></button>
                {classes.map((item) => {
                  const selected = selectedClasses?.[String(id)] === item.id
                  return <button type="button" key={item.id} aria-pressed={selected} aria-label={`${item.teacher_name}，${item.name}，${item.is_full ? t("已选满") : t("剩余{{p0}}个名额", { p0: item.remaining })}`} className={`choice-teacher ${selected ? 'is-selected' : ''}`} disabled={saving || refreshing || (!selected && item.is_full && !item.selected_by_me)} onClick={() => form.setFieldValue(['teaching_class_preferences', String(id)], item.id)}>
                    <span className="choice-seat-status" data-full={item.is_full}>{item.is_full ? t("已选满") : t("剩余 {{p0}} 人", { p0: item.remaining })}</span><span className="choice-avatar">{item.teacher_name.slice(0, 1)}</span><strong>{item.teacher_name}</strong><small>{item.name}</small>
                    <div className="choice-seat-meter"><span style={{ width: `${Math.min(100, item.capacity > 0 ? item.selected_count / item.capacity * 100 : 100)}%` }} /></div><span className="choice-seat-count">{t("已选")}{item.selected_count} {t("/ 上限")}{item.capacity} {t("人")}</span><span className="choice-teacher-action">{selected ? <><CheckOutlined /> {t("已选择")}</> : item.is_full ? t("名额已满") : t("选择这个班")}</span>
                  </button>
                })}</div>}
              {!locked && !classes.length && <p className="choice-no-classes">{t("本学科暂无可选教学班，将由学校统一安排。")}</p>}
            </div>
          })}
          {!locked && <p className="choice-seat-note"><ClockCircleOutlined /> {t("提交后预留班级名额，保存草稿不占名额。最终分班以教务安排为准。")}</p>}
        </section>}
      </div>
      <aside className="choice-summary" aria-label={t("我的选科组合")}><div className="choice-summary-top"><span>{locked ? <CheckCircleFilled /> : <ReadOutlined />}</span><div><h2>{locked ? t("已确认的组合") : t("我的选科组合")}</h2><p>{complete ? t("首选 1 门 + 再选 2 门") : t("选择后在这里核对")}</p></div></div>
        <div className="choice-combination" aria-live="polite">{selectedSubjects.length ? selectedSubjects.map((id, index) => <span key={id}>{index > 0 && <b>+</b>}<strong>{nameOf(id)}</strong></span>) : <span className="choice-placeholder">{t("等待选择科目")}</span>}</div>
        <div className="choice-summary-rows"><div><span>{t("首选科目")}</span><strong>{primarySubject === undefined ? t("待选择") : nameOf(primarySubject)}</strong></div><div><span>{t("再选科目")}</span><strong>{(secondarySubjects || []).length ? secondarySubjects?.map(nameOf).join('、') : t("待选择")}</strong></div></div>
        {selectionMode === 'teacher' && <div className="choice-summary-teachers">{selectedSubjects.map((id) => <div key={id}><span>{nameOf(id)}</span><strong>{selectedClass(id)?.teacher_name || t("学校安排")}</strong></div>)}</div>}
        <div className="choice-progress"><span style={{ width: `${Math.min(100, selectedSubjects.length / 3 * 100)}%` }} /></div>
        <p className="choice-summary-hint">{locked ? t("选科已通过审核，结果已锁定") : complete ? t("科目已选齐，核对后即可提交") : t("已选 {{p0}} / 3 门，请继续选择", { p0: selectedSubjects.length })}</p>
        {locked ? <div className="choice-lock-note"><LockOutlined /> {t("如需修改，请联系班主任")}</div> : <div className="choice-submit-actions"><Button type="primary" size="large" icon={<SendOutlined />} block disabled={!complete || refreshing} loading={saving} onClick={() => setConfirmOpen(true)}>{t("核对并提交")}</Button><Button size="large" icon={<SaveOutlined />} block disabled={!complete || refreshing} loading={saving} onClick={() => void submit('draft')}>{t("保存草稿")}</Button><small>{t("提交后等待班主任审核，审核通过后不可自行修改。")}</small></div>}
        <div className="choice-scheme"><span>{t("当前选科方案")}</span><strong>{scheme.name}</strong></div>
      </aside></div>
    </Form>
    <Modal title={t("核对你的选科")} open={confirmOpen} onCancel={() => { if (!saving) setConfirmOpen(false) }} onOk={() => void submit('confirmed')} confirmLoading={saving} okText={t("确认提交")} cancelText={t("继续修改")}>
      <p className="choice-confirm-combo">{selectedSubjects.map(nameOf).join(' + ')}</p>
      {selectionMode === 'teacher' && selectedSubjects.map((id) => <p key={id}>{nameOf(id)}：{selectedClass(id) ? `${selectedClass(id)?.teacher_name} · ${selectedClass(id)?.name}` : t("学校统一安排")}</p>)}
      <Alert type="info" showIcon message={t("提交后由班主任审核，审核通过后选科将锁定。")} />
    </Modal>
  </div></main>
}
