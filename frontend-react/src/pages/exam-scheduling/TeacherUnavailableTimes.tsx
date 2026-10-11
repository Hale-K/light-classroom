import { Button, Select, Space, TimePicker } from 'antd'
import dayjs from 'dayjs'

/** Weekly windows share the persisted availability list with date/session keys. */
export default function TeacherUnavailableTimes({ value = [], onChange = () => {} }: { value?: string[]; onChange?: (value: string[]) => void }) {
  const windows = value.filter(item => item.startsWith('weekly#'))
  const other = value.filter(item => !item.startsWith('weekly#'))
  const update = (index: number, weekday: string, start: string, end: string) => {
    onChange([...other, ...windows.map((item, i) => i === index ? `weekly#${weekday}#${start}#${end}` : item)])
  }
  return <div>
    <p className="es-muted">例如：周三13:00–18:00有事，系统会避开所有与该时段重叠的监考。适用于本次考试。</p>
    {windows.map((item, index) => {
      const [, weekday, start, end] = item.split('#')
      return <Space wrap key={index} style={{ marginBottom: 8 }}>
        <Select aria-label={`不可监考星期${index + 1}`} value={weekday} onChange={day => update(index, day, start, end)} options={['一', '二', '三', '四', '五', '六', '日'].map((day, i) => ({ value: String(i + 1), label: `周${day}` }))} />
        <TimePicker.RangePicker aria-label={`不可监考时间${index + 1}`} format="HH:mm" allowClear={false} value={[dayjs(`2000-01-01T${start}`), dayjs(`2000-01-01T${end}`)]} onChange={times => { if (times?.[0] && times[1]) update(index, weekday, times[0].format('HH:mm'), times[1].format('HH:mm')) }} />
        <Button onClick={() => onChange([...other, ...windows.filter((_, i) => i !== index)])}>删除时段</Button>
      </Space>
    })}
    <Button disabled={windows.length >= 20} onClick={() => onChange([...value, 'weekly#3#13:00#18:00'])}>＋ 添加每周不可监考时段</Button>
  </div>
}
