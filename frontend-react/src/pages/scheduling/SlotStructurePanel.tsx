import { Button, InputNumber, Select, Space, Tag } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import type { SchedulingGridConfig } from '@/types'
import { normalizeGridConfig, resolveEveningStartPeriod } from './scheduling-model'

interface Props {
  config: SchedulingGridConfig
  academicYear: string
  term: string
  saving?: boolean
  onChange: (config: SchedulingGridConfig) => void
  onSave: () => void
}

const DAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const ZERO_PROFILE = () => [0, 0, 0, 0, 0, 0, 0]

export default function SlotStructurePanel({ config, academicYear, term, saving, onChange, onSave }: Props) {
  const dailyPeriods = Array.from({ length: 7 }, (_, index) => config.daily_periods[index] ?? 0)
  const oddProfile = Array.from({ length: 7 }, (_, index) => config.evening_daily_periods_odd[index] ?? 0)
  const evenProfile = Array.from({ length: 7 }, (_, index) => config.evening_daily_periods_even[index] ?? 0)
  const eveningEnabled = oddProfile.some(Boolean) || evenProfile.some(Boolean)
  const dayCount = dailyPeriods.filter(Boolean).length
  const formalSlotCount = dailyPeriods.reduce((sum, value) => sum + value, 0)
  const eveningSlotCount = Math.max(...oddProfile, ...evenProfile, 0)
  const eveningStart = resolveEveningStartPeriod(config)

  const updateDailyPeriod = (index: number, value: number | null) => {
    const next = [...dailyPeriods]
    next[index] = value ?? 0
    onChange(normalizeGridConfig({ ...config, daily_periods: next }))
  }

  const updateProfile = (profile: 'odd' | 'even', index: number, value: number | null) => {
    const next = profile === 'odd' ? [...oddProfile] : [...evenProfile]
    next[index] = Math.max(0, Math.min(3, value ?? 0))
    onChange(normalizeGridConfig({
      ...config,
      ...(profile === 'odd' ? { evening_daily_periods_odd: next } : { evening_daily_periods_even: next }),
    }))
  }

  const disableSpecialSlots = () => onChange(normalizeGridConfig({
    ...config,
    enable_evening: false,
    evening_daily_periods_odd: ZERO_PROFILE(),
    evening_daily_periods_even: ZERO_PROFILE(),
  }))

  return (
    <section className="slot-structure-panel">
      <div className="slot-structure-head">
        <div>
          <div className="slot-structure-kicker">SLOT STRUCTURE / 课位结构</div>
          <h2>先确定课位，再编写规则</h2>
          <p>这里定义每个教学日有多少个具体课位。规则编辑器会读取这些课位，避免把“白天课”“晚课”当成无法校验的文字。</p>
        </div>
        <Space direction="vertical" align="end" size={10}>
          <Tag color="blue">{academicYear} · 第 {term} 学期</Tag>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={onSave}>生成并保存课位结构</Button>
        </Space>
      </div>

      <div className="slot-structure-summary" aria-label="课位结构摘要">
        <div><span>教学日</span><strong>{dayCount} 天</strong><small>按每天课位数启用</small></div>
        <div><span>正式课位</span><strong>{formalSlotCount} 个</strong><small>各日合计</small></div>
        <div><span>每日上限</span><strong>{Math.max(...dailyPeriods, 0)} 节</strong><small>用于生成矩阵</small></div>
        <div>
          <span>特殊课位</span>
          <strong>{eveningEnabled ? `${eveningSlotCount} 节` : '未启用'}</strong>
          <small>{eveningStart ? `接在第 ${eveningStart} 节起` : '单双周分别配置'}</small>
        </div>
      </div>

      <div className="slot-structure-section">
        <div className="slot-structure-section-head">
          <div><span className="slot-structure-index">01</span><div><h3>正式课位</h3><p>每一天单独设置数量，0 表示当天不启用。第 1 节到当天最后一节都是明确课位。</p></div></div>
          <Tag>最多 12 节 / 天</Tag>
        </div>
        <div className="slot-day-grid">
          {DAY_NAMES.map((day, index) => (
            <label className={dailyPeriods[index] ? 'is-active' : ''} key={day}>
              <span>{day}</span>
              <InputNumber min={0} max={12} value={dailyPeriods[index]} addonAfter="节" onChange={(value) => updateDailyPeriod(index, value)} />
              <small>{dailyPeriods[index] ? `第 1—${dailyPeriods[index]} 节` : '当天不启用'}</small>
            </label>
          ))}
        </div>
      </div>

      <div className="slot-structure-section slot-structure-special">
        <div className="slot-structure-section-head">
          <div><span className="slot-structure-index">02</span><div><h3>特殊课位</h3><p>例如晚课、晚自习等独立课位。先配置每周具体数量，规则中只引用已经存在的课位。</p></div></div>
          {eveningEnabled ? <Button size="small" onClick={disableSpecialSlots}>清空特殊课位</Button> : <Tag>未配置</Tag>}
        </div>
        <div className="slot-profile-table">
          <div className="slot-profile-row slot-profile-header"><strong>周次</strong>{DAY_NAMES.map((day) => <span key={day}>{day}</span>)}<em>合计</em></div>
          {([['单周', oddProfile, 'odd'], ['双周', evenProfile, 'even']] as const).map(([label, profile, key]) => (
            <div className="slot-profile-row" key={key}>
              <strong>{label}</strong>
              {DAY_NAMES.map((day, index) => <InputNumber key={day} aria-label={`${label}${day}特殊课位数`} min={0} max={3} value={profile[index]} onChange={(value) => updateProfile(key, index, value)} />)}
              <em>{profile.reduce((sum, value) => sum + value, 0)} 节</em>
            </div>
          ))}
        </div>
        <div className="slot-structure-note">
          特殊课位自动接在当天正式课位之后
          {eveningStart ? `（当前为第 ${eveningStart} 节，随正式课上限变化，不写死）` : ''}
          ；如不使用单双周特殊课位，保持两行全为 0 即可。
        </div>
        <div className="slot-structure-parity"><span>首周周次</span><Select value={config.first_week_parity} options={[{ value: 'odd', label: '单周' }, { value: 'even', label: '双周' }]} onChange={(value) => onChange({ ...config, first_week_parity: value })} /><span>学期首周周一由系统按需记录，用于单双周换算。</span></div>
      </div>
    </section>
  )
}
