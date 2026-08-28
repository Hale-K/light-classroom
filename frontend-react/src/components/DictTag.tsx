import { Tag } from 'antd'
import type { Dict } from '@/types/dict'

interface DictTagProps {
  dict: Dict
  value?: string | number | null
}

/**
 * 统一枚举标签：集中字典 → 预设色 / 自定义底色（bg+border）标签。
 * 未知值兜底显示原值（灰 Tag），空值显示 '—'。
 */
export default function DictTag({ dict, value }: DictTagProps) {
  const key = value != null ? String(value) : undefined
  const item = key != null ? dict[key] : undefined
  if (!item) {
    return <Tag style={{ marginInlineEnd: 0 }}>{key ?? '—'}</Tag>
  }
  if (item.bg) {
    return (
      <Tag
        style={{
          color: item.color,
          background: item.bg,
          borderColor: item.border,
          borderRadius: 4,
          marginInlineEnd: 0,
        }}
      >
        {item.label}
      </Tag>
    )
  }
  return (
    <Tag color={item.color ?? 'default'} style={{ marginInlineEnd: 0 }}>
      {item.label}
    </Tag>
  )
}
