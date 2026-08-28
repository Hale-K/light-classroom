import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Key } from 'react'
import { App, Button, Empty, Form, Input, Modal, Select, Switch, Tree } from 'antd'
import type { DataNode } from 'antd/es/tree'
import { organizationApi, orgApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import Icon from '@/components/Icon'
import type { OrganizationTreeResult, OrganizationUnit, OrganizationUnitType } from '@/types'
import { academicYearOptions } from '@/academicYear'
import { flattenOrganizationUnits, organizationExpandedKeys } from './tree-utils'

interface UnitFormValues {
  name: string
  unit_type: OrganizationUnitType
  parent_id?: number
  academic_year?: string
  cohort_label?: string
  grade_id?: number
  /** 表单专用:是否设为年级部(挂到年级管理中心),提交前剥离 */
  is_grade?: boolean
  /** 表单专用:是否设为年级管理中心,提交前剥离 */
  is_grade_center?: boolean
}

const TYPE_LABEL: Record<OrganizationUnitType, string> = {
  department: '职能部门', grade_group: '年级部', subject_group: '学科组', admin_class: '行政班',
}

function toTreeData(units: OrganizationUnit[]): DataNode[] {
  return units.map((unit) => ({
    key: unit.id,
    title: <span className="zh-org-tree-title"><span>{unit.name}</span><small>{unit.member_count}</small></span>,
    children: toTreeData(unit.children),
  }))
}

export default function OrganizationView({ embedded = false }: { embedded?: boolean }) {
  const { message, modal } = App.useApp()
  const [data, setData] = useState<OrganizationTreeResult>()
  const [grades, setGrades] = useState<Array<{ id: number; name: string }>>([])
  const [selectedId, setSelectedId] = useState<number>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<OrganizationUnit>()
  const [expandedKeys, setExpandedKeys] = useState<Key[]>(['school'])
  const [treeWidth, setTreeWidth] = useState(380)
  const [resizingTree, setResizingTree] = useState(false)
  const workspaceRef = useRef<HTMLDivElement>(null)
  const [form] = Form.useForm<UnitFormValues>()

  useEffect(() => {
    if (!resizingTree) return
    const onPointerMove = (event: PointerEvent) => {
      const left = workspaceRef.current?.getBoundingClientRect().left ?? 0
      setTreeWidth(Math.min(560, Math.max(280, event.clientX - left)))
    }
    const stopResize = () => setResizingTree(false)
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', stopResize)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    return () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', stopResize)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [resizingTree])

  const load = async () => {
    setLoading(true)
    try {
      const [result, gradeList] = await Promise.all([organizationApi.tree(), orgApi.grades()])
      setData(result)
      setGrades(gradeList)
      setExpandedKeys(organizationExpandedKeys(result.units))
    }
    catch (error) { message.error(error instanceof Error ? error.message : '组织机构加载失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  // 年级管理中心:优先取用户显式标记(TenantConfig),未标记时按名称兜底
  const [gradeCenterMarker, setGradeCenterMarker] = useState<{ unit_id: number | null; unit_name: string | null }>({ unit_id: null, unit_name: null })
  useEffect(() => {
    organizationApi.gradeCenter().then(setGradeCenterMarker).catch(() => {})
  }, [data])

  const units = useMemo(() => flattenOrganizationUnits(data?.units ?? []), [data])
  const gradeCenterId = gradeCenterMarker.unit_id
    ?? units.find((unit) => unit.name === '年级管理中心')?.id
  const yearOptions = useMemo(
    () => academicYearOptions(units.map((unit) => unit.academic_year)),
    [units],
  )
  const selected = units.find((unit) => unit.id === selectedId)
  const treeData: DataNode[] = [{
    key: 'school',
    title: <span className="zh-org-tree-title zh-org-school-title"><span>{data?.school.name ?? '当前学校'}</span><small>{units.length} 个组织</small></span>,
    children: toTreeData(data?.units ?? []),
  }]

  const startCreate = () => {
    setEditing(undefined)
    form.setFieldsValue({ name: '', unit_type: 'department', parent_id: selectedId, grade_id: undefined, is_grade: false, is_grade_center: false })
    setOpen(true)
  }
  const startEdit = () => {
    if (!selected) return
    setEditing(selected)
    form.setFieldsValue({
      name: selected.name, unit_type: selected.unit_type, parent_id: selected.parent_id ?? undefined, grade_id: selected.grade_id ?? undefined,
      academic_year: selected.academic_year ?? undefined, cohort_label: selected.cohort_label ?? undefined,
      is_grade: selected.unit_type === 'grade_group',
      is_grade_center: gradeCenterMarker.unit_id === selected.id,
    })
    setOpen(true)
  }
  const save = async () => {
    const values = await form.validateFields().catch(() => null)
    if (!values) return
    const { is_grade, is_grade_center, ...payload } = values
    if (!is_grade && payload.grade_id) {
      message.warning('只有年级部可以绑定对应年级')
      return
    }
    if (is_grade) {
      if (!gradeCenterId) {
        message.warning('未找到「年级管理中心」:请先在某个组织上开启「设为年级管理中心」')
        return
      }
      payload.unit_type = 'grade_group'
      payload.parent_id = gradeCenterId
    }
    setSaving(true)
    try {
      const unit = editing
        ? await organizationApi.updateUnit(editing.id, payload)
        : await organizationApi.createUnit(payload)
      if (is_grade_center) {
        await organizationApi.setGradeCenter(unit.id)
      }
      message.success(editing ? '组织节点已更新' : '组织节点已创建')
      setOpen(false)
      await load()
    } catch (error) { message.error(error instanceof Error ? error.message : '组织节点保存失败') }
    finally { setSaving(false) }
  }
  const archive = () => {
    if (!selected) return
    modal.confirm({ title: `归档“${selected.name}”`, content: '归档后不再出现在当前组织树中，已有业务记录不会删除。',
      okText: '确认归档', cancelText: '取消', onOk: async () => {
        await organizationApi.updateUnit(selected.id, { status: 'archived' })
        setSelectedId(undefined); await load(); message.success('组织节点已归档')
      } })
  }

  const createButton = <Button type="primary" onClick={startCreate}>新建组织</Button>
  return <div className={embedded ? 'personnel-pane' : 'zh-page'}>
    {embedded ? <div className="facility-subhead"><div><h3>组织机构</h3><p>维护部门、年级部、学科组及行政班的上下级关系。</p></div>{createButton}</div> : <><PageHeader title="组织机构" extra={createButton} /><p className="zh-page-desc">维护学校长期部门与当前学年的年级组织。年级部可绑定届和学年，历史节点采用归档而不是删除。</p></>}
    <div ref={workspaceRef} className="zh-organization-workspace" style={{ '--org-tree-width': `${treeWidth}px` } as CSSProperties}>
      <aside className="zh-organization-tree-panel" aria-label="学校组织树">
        <div className="zh-organization-panel-title"><Icon name="grid" size={16} /><strong>组织树</strong></div>
        <Tree blockNode treeData={treeData} expandedKeys={expandedKeys} onExpand={setExpandedKeys}
          selectedKeys={selectedId ? [selectedId] : ['school']}
          onSelect={(keys) => setSelectedId(typeof keys[0] === 'number' ? keys[0] : undefined)} />
      </aside>
      <div
        className={`zh-organization-resizer${resizingTree ? ' is-resizing' : ''}`}
        role="separator"
        aria-orientation="vertical"
        aria-label="调整组织树宽度"
        tabIndex={0}
        onPointerDown={(event) => { event.preventDefault(); setResizingTree(true) }}
        onKeyDown={(event) => {
          if (event.key === 'ArrowLeft') setTreeWidth((value) => Math.max(240, value - 20))
          if (event.key === 'ArrowRight') setTreeWidth((value) => Math.min(460, value + 20))
        }}
      />
      <section className="zh-organization-detail" aria-label="组织详情">
        {selected ? <>
          <div className="zh-organization-detail-head"><div><span>{TYPE_LABEL[selected.unit_type]}</span><h2>{selected.name}</h2></div>
            <div><Button onClick={startCreate}>创建下级</Button><Button onClick={startEdit}>修改</Button><Button danger onClick={archive}>归档</Button></div></div>
          <dl className="zh-organization-facts">
            <div><dt>当前成员</dt><dd>{selected.member_count} 人</dd></div>
            <div><dt>所属学年</dt><dd>{selected.academic_year || '长期有效'}</dd></div>
            <div><dt>对应届</dt><dd>{selected.cohort_label || '不限定'}</dd></div>
            <div><dt>组织状态</dt><dd>使用中</dd></div>
          </dl>
          <div className="zh-organization-next"><strong>下一步</strong><p>前往“岗位与权限”，为该组织任命负责人和成员。</p></div>
        </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={loading ? '正在加载组织机构' : '选择一个组织节点查看详情'} />}
      </section>
    </div>
    <Modal title={editing ? '修改组织' : '新建组织'} open={open} onCancel={() => setOpen(false)} onOk={() => void save()}
      okText="保存" cancelText="取消" confirmLoading={saving} width={520} forceRender>
      <Form form={form} layout="vertical">
        <Form.Item name="name" label="组织名称" rules={[{ required: true, whitespace: true, message: '请输入组织名称' }]}><Input maxLength={100} /></Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.is_grade_center !== next.is_grade_center || prev.is_grade !== next.is_grade}>
          {({ getFieldValue }) => {
            const isGradeCenterChecked = !!getFieldValue('is_grade_center')
            const centerTaken = gradeCenterMarker.unit_id != null && gradeCenterMarker.unit_id !== editing?.id
            return <Form.Item
              name="is_grade_center"
              label="设为年级管理中心"
              valuePropName="checked"
              extra={centerTaken && !isGradeCenterChecked
                ? `已由「${gradeCenterMarker.unit_name}」担任,全校只能有一个`
                : '全校唯一的枢纽节点;「年级部」开关会把单元自动挂到它下面'}
            >
              <Switch
                checkedChildren="管理中心"
                unCheckedChildren="普通组织"
                disabled={centerTaken && !isGradeCenterChecked}
                onChange={(checked) => {
                  if (checked) form.setFieldValue('is_grade', false)
                }}
              />
            </Form.Item>
          }}
        </Form.Item>
        <Form.Item name="is_grade" label="设为年级部" valuePropName="checked" extra="开启后自动挂到「年级管理中心」下,并按年级部类型识别;师资调整、排课圈定都会认到它">
          <Switch
            checkedChildren="年级部"
            unCheckedChildren="普通组织"
            onChange={(checked) => {
              if (checked) {
                form.setFieldValue('is_grade_center', false)
                form.setFieldValue('unit_type', 'grade_group')
                if (gradeCenterId) form.setFieldValue('parent_id', gradeCenterId)
              } else {
                form.setFieldValue('unit_type', 'department')
                form.setFieldValue('parent_id', undefined)
              }
            }}
          />
        </Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.is_grade !== next.is_grade}>
          {({ getFieldValue }) => {
            const isGrade = !!getFieldValue('is_grade')
            return <>
              <Form.Item name="unit_type" label="组织类型" rules={[{ required: true }]}><Select disabled={!!editing || isGrade}
                options={Object.entries(TYPE_LABEL).map(([value, label]) => ({ value, label }))} /></Form.Item>
              <Form.Item name="parent_id" label="上级组织"><Select allowClear disabled={isGrade} placeholder={isGrade ? '年级管理中心(自动)' : '学校直属'}
                options={units.filter((unit) => unit.id !== editing?.id).map((unit) => ({ value: unit.id, label: unit.name }))} /></Form.Item>
            </>
          }}
        </Form.Item>
        <div className="zh-form-grid">
          <Form.Item name="academic_year" label="所属学年"><Select allowClear placeholder="选择学年；长期部门留空" options={yearOptions} /></Form.Item>
          <Form.Item name="cohort_label" label="对应届"><Input placeholder="如 2029届；非年级组织留空" /></Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, next) => prev.is_grade !== next.is_grade || prev.unit_type !== next.unit_type}>
          {({ getFieldValue }) => getFieldValue('is_grade') ? <Form.Item name="grade_id" label="对应年级" rules={[{ required: true, message: '请选择对应年级' }]}>
              <Select placeholder="选择高一年级 / 高二年级 / 高三年级" options={[
                ...grades.map((grade) => ({ label: grade.name, value: grade.id })),
              ]} />
            </Form.Item> : editing?.unit_type === 'grade_group' ? <Form.Item name="grade_id" label="对应年级" rules={[{ required: true, message: '请选择对应年级' }]}>
              <Select placeholder="选择高一年级 / 高二年级 / 高三年级" options={[
                ...grades.map((grade) => ({ label: grade.name, value: grade.id })),
              ]} />
            </Form.Item> : null}
          </Form.Item>
        </div>
      </Form>
    </Modal>
  </div>
}
