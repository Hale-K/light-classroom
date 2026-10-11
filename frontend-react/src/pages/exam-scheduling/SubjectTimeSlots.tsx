import { Alert } from 'antd'
import { CheckOutlined } from '@ant-design/icons'

interface Props {
  ids: number[]; subjects: Array<{ id: number; name: string }>
  sessions: Array<{ start_time: string; end_time: string }>
  value: Record<string, string>; disabled: boolean
  onChange: (value: Record<string, string>) => void
}

const periodName = (time: string) => time < '12:00' ? '上午' : time < '18:00' ? '下午' : '晚上'

export default function SubjectTimeSlots({ ids, subjects, sessions, value, disabled, onChange }: Props) {
  const ordered = [...sessions].sort((a, b) => a.start_time.localeCompare(b.start_time))
  const invalid = ids.some(id => value[id] && !ordered.some(s => s.start_time === value[id]))
  const choose = (id: number, start?: string) => {
    const next = { ...value }
    if (start) next[id] = start
    else delete next[id]
    onChange(next)
  }
  return <section className="es-time-board" aria-label="科目考试时段">
    <div className="es-time-board-heading"><strong>科目考在什么时候？</strong><p>{disabled ? '当前学校策略固定安排时间。切换普通学校考试后可指定科目时段。' : '点击时间格指定场次，例如语文选上午。未指定的科目由系统安排。'}</p></div>
    {invalid && <Alert showIcon type="warning" message="部分科目选择的时段已变更，请重新选择或改为自动安排。" />}
    <div className="es-time-board-scroll"><table className="es-time-matrix">
      <caption className="es-sr-only">每科选择每天的考试时段，具体日期由系统结合顺序和规则生成。</caption>
      <thead><tr><th scope="col">考试科目</th><th scope="col" className="es-auto-head"><span>自动安排</span><small>不指定时段</small></th>{ordered.map((s, i) => <th scope="col" key={i}><span>{periodName(s.start_time)}</span><strong>{s.start_time}–{s.end_time}</strong></th>)}</tr></thead>
      <tbody>{ids.map(id => {
        const name = subjects.find(s => s.id === id)?.name || `科目${id}`
        return <tr key={id}><th scope="row">{name}{value[id] && !ordered.some(s => s.start_time === value[id]) && <small className="es-time-invalid">原时段 {value[id]} 已变更</small>}</th>
          <td><button type="button" aria-label={`${name}自动安排`} aria-pressed={!value[id]} disabled={disabled} className={`es-time-choice is-auto${!value[id] ? ' is-selected' : ''}`} onClick={() => choose(id)}>{!value[id] ? <><CheckOutlined /> 自动</> : '自动'}</button></td>
          {ordered.map((s, i) => <td key={i}><button type="button" aria-label={`${name}安排在${periodName(s.start_time)}${s.start_time}至${s.end_time}`} aria-pressed={value[id] === s.start_time} disabled={disabled || !s.start_time || !s.end_time || s.start_time >= s.end_time} className={`es-time-choice${value[id] === s.start_time ? ' is-selected' : ''}`} onClick={() => choose(id, s.start_time)}>{value[id] === s.start_time ? <><CheckOutlined /> 已指定</> : '选择此时段'}</button></td>)}
        </tr>
      })}</tbody>
    </table></div>
    {!ids.length && <p className="es-muted">先选择考试科目。</p>}
    <p className="es-time-board-note">多个科目选同一时段时，将按科目顺序分配到不同日期；保存后查看完整日程。</p>
  </section>
}
