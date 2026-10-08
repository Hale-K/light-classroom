/** 学段 → 年级/学科/教材版本/章节 的公共表单段（课件库与工作台共用）。 */
import { useMemo } from 'react'
import { Form, Input, Select } from 'antd'
import type { FormInstance } from 'antd'
import type { CourseCatalog } from '@/types'

export default function CourseScopeFields({
  catalog,
  form,
  compact = false,
}: {
  catalog: CourseCatalog | null
  form: FormInstance
  compact?: boolean
}) {
  const stage = Form.useWatch('stage', form)
  const meta = useMemo(() => catalog?.stages.find((s) => s.name === stage), [catalog, stage])
  const gap = compact ? { marginBottom: 10 } : undefined
  return (
    <>
      <Form.Item name="stage" label="学段" rules={[{ required: true, message: '请选择学段' }]} style={gap}>
        <Select
          placeholder="小学 / 初中 / 高中"
          allowClear
          options={(catalog?.stages ?? []).map((s) => ({ value: s.name, label: s.name }))}
          onChange={() => form.setFieldsValue({ grade_name: undefined, subject_name: undefined })}
        />
      </Form.Item>
      <Form.Item name="grade_name" label="年级" style={gap}>
        <Select placeholder="选择年级" allowClear options={(meta?.grades ?? []).map((g) => ({ value: g, label: g }))} />
      </Form.Item>
      <Form.Item name="subject_name" label="学科" style={gap}>
        <Select
          placeholder="选择学科"
          allowClear
          showSearch
          optionFilterProp="label"
          options={(meta?.subjects ?? []).map((s) => ({ value: s, label: s }))}
        />
      </Form.Item>
      <Form.Item name="textbook_version" label="教材版本" style={gap}>
        <Select
          placeholder="可选"
          allowClear
          showSearch
          optionFilterProp="label"
          options={(catalog?.textbook_versions ?? []).map((v) => ({ value: v, label: v }))}
        />
      </Form.Item>
      <Form.Item name="chapter" label="章节 / 课题" style={gap}>
        <Input placeholder="如：第三章 第二节 压强" allowClear />
      </Form.Item>
    </>
  )
}
