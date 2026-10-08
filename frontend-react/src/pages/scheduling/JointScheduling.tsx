import { useState } from 'react'
import { Alert, App, Button, Checkbox, InputNumber, Modal, Select, Space } from 'antd'
import { gaokaoApi } from '@/api'
import JointPreview from './JointPreview'

type Props = {
  gradeId?: number
  gradeName?: string
  gradeOptions?: { value: number; label: string }[]
  academicYear: string
  term: string
  disabled?: boolean
  onSaved: (gradeId: number) => void
}

/** One preview token binds the visible settings and the server-validated candidate. */
export default function JointScheduling({ gradeId, gradeName, gradeOptions, academicYear, term, disabled, onSaved }: Props) {
  const { message } = App.useApp()
  const [open, setOpen] = useState(false)
  const [previewGradeId, setPreviewGradeId] = useState(gradeId)
  const scopeName = gradeOptions?.find(g => g.value === previewGradeId)?.label ?? gradeName ?? '当前年级'
  const [capacity, setCapacity] = useState(45)
  const [capacityOverflow, setCapacityOverflow] = useState(5)
  const [weekdays, setWeekdays] = useState([1, 2, 3, 4, 5, 6])
  const [lastPeriod, setLastPeriod] = useState(7)
  const [busy, setBusy] = useState<'preview' | 'save'>()
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof gaokaoApi.previewRegroupPlan>>>()
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const invalidate = () => { setPreview(undefined); setConfirmed(false); setError('') }

  const runPreview = async () => {
    if (!previewGradeId) return
    invalidate(); setBusy('preview')
    try {
      setPreview(await gaokaoApi.previewRegroupPlan({ grade_id: previewGradeId, academic_year: academicYear,
        term, capacity, capacity_overflow: capacityOverflow, weekdays,
        periods: Array.from({ length: lastPeriod }, (_, i) => i + 1) }))
    } catch (e) { setError(e instanceof Error ? e.message : '预览失败') }
    finally { setBusy(undefined) }
  }
  const save = async () => {
    if (!previewGradeId || !preview || !confirmed) return
    setBusy('save'); setError('')
    try {
      await gaokaoApi.saveRegroupPlan({ grade_id: previewGradeId, academic_year: academicYear, term,
        preview_token: preview.preview_token, confirm_replace: true })
      message.success('新分组、行政课和走班课表已保存')
      setOpen(false); invalidate(); onSaved(previewGradeId)
    } catch (e) {
      invalidate(); setError(e instanceof Error ? e.message : '保存失败，请重新预览')
    } finally { setBusy(undefined) }
  }

  const gradeControl = <label className="joint-grade-filter">年级<Select aria-label="预览年级"
    disabled={!!busy} value={previewGradeId} options={gradeOptions ?? (gradeId ? [{ value: gradeId, label: gradeName ?? '当前年级' }] : [])}
    onChange={value => { setPreviewGradeId(value); invalidate() }} /></label>
  return <>
    <Button type="primary" size="large" disabled={disabled || !gradeId} onClick={() => { setPreviewGradeId(gradeId); invalidate(); setOpen(true) }}>联合排课</Button>
    <Modal title={`${scopeName} · 联合排课`} open={open} width={preview ? 1160 : 760} className="joint-preview-modal"
      closable={!busy} maskClosable={!busy} keyboard={!busy}
      onCancel={() => { if (!busy) setOpen(false) }}
      footer={<Space wrap>
        <Button disabled={!!busy} onClick={() => setOpen(false)}>取消</Button>
        <Button loading={busy === 'preview'} disabled={!!busy || !previewGradeId || !weekdays.length} onClick={runPreview}>预览课表</Button>
        <Button type="primary" loading={busy === 'save'} disabled={!!busy || !preview?.lessons || !confirmed} onClick={save}>确认保存</Button>
      </Space>}>
      <Space direction="vertical" size="middle" className="w-full">
        <span>{academicYear} · 第{term}学期；重新分教学班，同时排行政课和走班课；行政班归属和选科不变。</span>
        {!preview && <div className="joint-preview-filters">{gradeControl}<span className="joint-preview-note">切换年级后需重新预览；不会保存或覆盖原课表。</span></div>}
        <details open={!preview} className="joint-preview-settings">
        <summary>排课设置 · 班额 {capacity} 人（允许 +{capacityOverflow} 人）· 每天至少排满 {lastPeriod} 节（点击展开）</summary>
        <Space wrap>
          <label>教学班人数上限 <InputNumber aria-label="教学班人数上限" min={1} max={100} precision={0} value={capacity}
            disabled={!!busy} onChange={v => { setCapacity(v ?? 45); invalidate() }} /></label>
          <label>每班允许超出 <InputNumber aria-label="每班允许超出人数" min={0} max={10} precision={0} value={capacityOverflow}
            disabled={!!busy} onChange={v => { setCapacityOverflow(v ?? 5); invalidate() }} /> 人</label>
          <label>每天至少从第1节排到 <InputNumber aria-label="每天最低排满节次" min={1} max={12} precision={0} value={lastPeriod}
            disabled={!!busy} onChange={v => { setLastPeriod(v ?? 7); invalidate() }} /> 节</label>
        </Space>
        <Select aria-label="排课星期" mode="multiple" value={weekdays} disabled={!!busy} className="w-full"
          options={['周一', '周二', '周三', '周四', '周五', '周六'].map((label, i) => ({ value: i + 1, label }))}
          onChange={v => { setWeekdays(v.sort((a, b) => a - b)); invalidate() }} />
        <Alert type="info" showIcon message={`所选日期第1–${lastPeriod}节必须有实际课程；多出的课时可排到基础课位中开放的其他白天节次。`}
          description="这里设置最低排满范围，不要求周总课时刚好等于该范围，也不会创建或修改规则。课时上限按保存的课位配置计算。" />
        </details>
        {busy === 'preview' && <Alert type="info" showIcon message="正在联合计算分组与课表，请稍候…" />}
        {error && <Alert type="error" showIcon message={error} />}
        {preview && <>
          <Alert type="success" showIcon message="预览通过 · 尚未保存"
            description={`${preview.student_count}名学生 · ${preview.class_count}个教学班；所选节次全部有课，冲突、课时和用户规则校验通过。`} />
          <JointPreview key={preview.preview_token} preview={preview} gradeControl={gradeControl} />
          <Checkbox checked={confirmed} disabled={!!busy} onChange={e => setConfirmed(e.target.checked)}>
            替换本年级、本学期的教学班和课表，不修改用户规则，不备份旧数据。
          </Checkbox>
        </>}
      </Space>
    </Modal>
  </>
}
