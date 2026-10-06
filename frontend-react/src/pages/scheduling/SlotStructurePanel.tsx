import { useEffect, useState } from 'react'
import { Button, Modal, Radio, Select, Segmented, Slider, Space, Spin, Tag } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import type { Grade, SchedulingGridConfig } from '@/types'
import { normalizeGridConfig, resolveEveningStartPeriod } from './scheduling-model'
import './slot-structure-sliders.css'

interface Props {
  config: SchedulingGridConfig
  academicYear: string
  term: string
  gradeId?: number
  grades?: Grade[]
  configured?: boolean
  loading?: boolean
  saving?: boolean
  onGradeChange?: (id: number) => void
  onChange: (config: SchedulingGridConfig) => void
  onSave: () => void
}
const DAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

export default function SlotStructurePanel({ config, academicYear, term, gradeId, grades = [], configured, loading, saving, onGradeChange, onChange, onSave }: Props) {
  const [editing, setEditing] = useState<{ day: number; period: number } | null>(null)
  const [slotMode, setSlotMode] = useState<'all' | 'odd' | 'even' | 'disabled'>('all')
  const [parity, setParity] = useState<'odd' | 'even'>('odd')
  useEffect(() => { setEditing(null); setParity('odd') }, [gradeId, academicYear, term])
  const daily = Array.from({ length: 7 }, (_, i) => config.daily_periods[i] ?? 0)
  const odd = Array.from({ length: 7 }, (_, i) => config.evening_daily_periods_odd[i] ?? 0)
  const even = Array.from({ length: 7 }, (_, i) => config.evening_daily_periods_even[i] ?? 0)
  const formalMax = Math.max(...daily, 0)
  const specialMax = Math.max(...odd, ...even, 0)
  const specialStart = resolveEveningStartPeriod(config)
  const rows = Math.max(formalMax, specialStart ? specialStart + specialMax - 1 : 0)
  const changeDay = (i: number, value: number) => {
    const next = [...daily]; next[i] = value
    const shift = Math.max(...next) - formalMax
    // Evening positions follow the formal maximum; preserve other days' per-slot modes.
    const overrides = (config.slot_overrides ?? []).flatMap((slot) => {
      if (slot.period > formalMax) return [{ ...slot, period: slot.period + shift }]
      return slot.weekday === i + 1 && slot.period > value ? [] : [slot]
    })
    onChange(normalizeGridConfig({ ...config, daily_periods: next, slot_overrides: overrides }))
  }
  const changeSpecial = (kind: 'odd' | 'even', i: number, value: number) => {
    const next = [...(kind === 'odd' ? odd : even)]; next[i] = value
    onChange(normalizeGridConfig({ ...config, enable_evening: false,
      slot_overrides: (config.slot_overrides ?? []).filter((slot) => slot.weekday !== i + 1 || slot.period <= formalMax),
      ...(kind === 'odd' ? { evening_daily_periods_odd: next } : { evening_daily_periods_even: next }) }))
  }
  const slotType = (day: number, period: number, leg: 'odd' | 'even') => {
    const override = config.slot_overrides?.find((slot) => slot.weekday === day && slot.period === period && slot.week_parity === leg)
    if (override) return override.slot_type
    if (period <= daily[day - 1]) return 'daytime'
    const profile = leg === 'odd' ? odd : even
    return specialStart !== null && period >= specialStart && period < specialStart + profile[day - 1] ? 'evening' : 'disabled'
  }
  const editSlot = (day: number, period: number) => {
    const oddOn = slotType(day, period, 'odd') !== 'disabled'
    const evenOn = slotType(day, period, 'even') !== 'disabled'
    setSlotMode(oddOn && evenOn ? 'all' : oddOn ? 'odd' : evenOn ? 'even' : 'disabled')
    setEditing({ day, period })
  }
  const applySlot = () => {
    if (!editing) return
    const { day, period } = editing
    const kind = period <= daily[day - 1] ? 'daytime' : 'evening'
    const overrides = (config.slot_overrides ?? []).filter((slot) => slot.weekday !== day || slot.period !== period)
    for (const leg of ['odd', 'even'] as const) overrides.push({ weekday: day, period, week_parity: leg, slot_type: slotMode === 'all' || slotMode === leg ? kind : 'disabled' })
    onChange({ ...config, slot_overrides: overrides })
    setEditing(null)
  }
  return <section className="slot-structure-panel slot-slider-panel">
    <div className="slot-slider-toolbar">
      <Space wrap>
        <Select aria-label="基础课位年级" className="slot-slider-grade" value={gradeId} disabled={loading || saving}
          options={grades.map((grade) => ({ value: grade.id, label: grade.name }))} onChange={onGradeChange} />
        <Tag>{academicYear} · 第 {term} 学期</Tag>
        <span className="slot-slider-save-state">{configured ? '本年级已配置' : '本年级尚未保存'}</span>
      </Space>
      <Button type="primary" icon={<SaveOutlined />} loading={saving} disabled={loading || !gradeId || !daily.some(Boolean)} onClick={onSave}>保存课位结构</Button>
    </div>
    <Spin spinning={loading}>
      <div className="slot-slider-layout">
        <section className="slot-structure-section slot-slider-controls">
          <div className="slot-slider-heading"><h3>每日正式课位</h3><p>拖动滑块设置节数，0 表示当天不启用。</p></div>
          {DAYS.map((day, i) => <div className="slot-slider-day" key={day}>
            <div><strong>{day}</strong><span>{daily[i] ? <><b>{daily[i]}</b> 节</> : '不启用'}</span></div>
            <Slider ariaLabelForHandle={`${day}正式课位数`} min={0} max={12 - specialMax} step={1} value={daily[i]} disabled={saving || loading}
              marks={{ 0: '0', [12 - specialMax]: String(12 - specialMax) }} onChange={(value) => changeDay(i, value)} />
          </div>)}
          <div className="slot-slider-total">{daily.filter(Boolean).length} 个教学日 · 每周 <strong>{daily.reduce((a, b) => a + b, 0)}</strong> 个正式课位</div>
        </section>
        <section className="slot-structure-section slot-slider-preview">
          <div className="slot-slider-preview-head"><div className="slot-slider-heading"><h3>一周课位预览</h3><p>拖动滑块批量设置，点击课位单独设置周次。</p></div>
            <Segmented aria-label="课位预览周次" value={parity} options={[{ label: '单周', value: 'odd' }, { label: '双周', value: 'even' }]} onChange={(value) => setParity(value as 'odd' | 'even')} />
          </div>
          <div className="slot-slider-legend"><span><i className="is-formal" />正式课位</span><span><i className="is-special" />晚自习</span><span>— 不启用</span><span>单 / 双 · 仅对应周次启用</span></div>
          <div className="slot-slider-matrix-scroll"><table className="slot-slider-matrix"><thead><tr><th>节次</th>{DAYS.map((day) => <th key={day}>{day}</th>)}</tr></thead>
            <tbody>{Array.from({ length: rows }, (_, i) => i + 1).map((period) => <tr key={period}><th>第 {period} 节</th>{DAYS.map((day, i) => {
              const kind = slotType(i + 1, period, parity)
              const formal = kind === 'daytime'
              const special = kind === 'evening'
              const editable = period <= daily[i] || (specialStart !== null && period >= specialStart && period < specialStart + Math.max(odd[i], even[i]))
              const oddOn = slotType(i + 1, period, 'odd') !== 'disabled'
              const evenOn = slotType(i + 1, period, 'even') !== 'disabled'
              const badge = oddOn !== evenOn ? oddOn ? '单' : '双' : ''
              return <td key={day}><button type="button" disabled={saving || loading || !editable} onClick={() => editSlot(i + 1, period)}
                className={formal ? 'is-formal' : special ? 'is-special' : 'is-off'}
                aria-label={`${parity === 'odd' ? '单周' : '双周'}${day}第${period}节${formal ? '正式课位' : special ? '晚自习' : '不启用'}`}>{formal ? '正式' : special ? '晚自习' : '—'}{badge && <small>{badge}</small>}</button></td>
            })}</tr>)}</tbody></table></div>
          {!rows && <p className="slot-slider-no-days">尚未启用任何课位，请拖动左侧滑块。</p>}
          <div className="slot-slider-preview-note">课位定义可排课的时间，不代表已安排课程。各年级、各学期独立保存。</div>
        </section>
      </div>
      <section className="slot-structure-section slot-slider-special">
        <div className="slot-slider-preview-head"><div className="slot-slider-heading"><h3>晚自习</h3><p>接在正式课上限之后，单周和双周分别设置。</p></div>
          <Button disabled={saving || loading || !specialMax} onClick={() => onChange(normalizeGridConfig({ ...config, enable_evening: false, slot_overrides: (config.slot_overrides ?? []).filter((slot) => slot.period <= formalMax), evening_daily_periods_odd: [0,0,0,0,0,0,0], evening_daily_periods_even: [0,0,0,0,0,0,0] }))}>清空晚自习</Button>
        </div>
        <div className="slot-special-slider-grid">{DAYS.map((day, i) => <div className="slot-special-slider-day" key={day}><strong>{day}</strong>
          {(['odd', 'even'] as const).map((kind) => <div key={kind}><label>{kind === 'odd' ? '单周' : '双周'}</label><Slider ariaLabelForHandle={`${kind === 'odd' ? '单周' : '双周'}${day}晚自习数`} min={0} max={Math.min(3, 12 - formalMax)} step={1}
            value={kind === 'odd' ? odd[i] : even[i]} disabled={saving || loading || formalMax === 12} onChange={(value) => changeSpecial(kind, i, value)} /><span>{(kind === 'odd' ? odd[i] : even[i])} 节</span></div>)}
        </div>)}</div>
        <div className="slot-slider-parity"><span>首周周次</span><Select aria-label="学期首周周次" value={config.first_week_parity} disabled={saving || loading} options={[{ value: 'odd', label: '单周' }, { value: 'even', label: '双周' }]} onChange={(value) => onChange({ ...config, first_week_parity: value })} /><span>正式与晚自习合计不超过每日 12 节。</span></div>
      </section>
    </Spin>
    <Modal title={editing ? `${DAYS[editing.day - 1]} · 第 ${editing.period} 节${editing.period > formalMax ? ' · 晚自习' : ''}` : '课位设置'}
      open={!!editing} onCancel={() => setEditing(null)} onOk={applySlot} okText="应用到预览" cancelText="取消">
      <p>选择这个课位在哪些周次启用，保存课位结构后生效。</p>
      <Radio.Group value={slotMode} onChange={(e) => setSlotMode(e.target.value)} options={[
        { label: '每周', value: 'all' }, { label: '仅单周', value: 'odd' }, { label: '仅双周', value: 'even' }, { label: '停用', value: 'disabled' },
      ]} />
    </Modal>
  </section>
}
