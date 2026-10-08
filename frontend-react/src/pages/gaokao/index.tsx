import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, App, Button, Card, Checkbox, Dropdown, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag } from 'antd'
import {
  ApartmentOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  ReadOutlined,
  TeamOutlined,
  ThunderboltFilled,
} from '@ant-design/icons'
import { authApi, gaokaoApi } from '@/api'
import type { GaokaoOverview } from '@/api'
import PageHeader from '@/components/PageHeader'
import EmptyState from '@/components/EmptyState'
import TeachingClassResults from './teaching-class-results'
import { useAuthStore } from '@/store/auth'
import './index.css'

type GaokaoMode = '3+1+2' | '3+3' | 'traditional'

const MODE_TITLE: Record<GaokaoMode, string> = {
  '3+1+2': '3+1+2 选科与走班',
  '3+3': '3+3 选科与走班',
  traditional: '传统文理分科',
}

const WORKFLOW_STEPS = [
  { code: 'exploration', label: '探索准备', note: '高一上：生涯规划、学科体验与成绩分析' },
  { code: 'intention', label: '意向与确认', note: '高一下：模拟填报、资源测算、正式确认与预分班' },
  { code: 'effective', label: '正式实施', note: '高二起：行政班与教学班双轨运行' },
] as const

export default function GaokaoView() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const user = useAuthStore((state) => state.user)

  const [academicYear, setAcademicYear] = useState('2026-2027')
  const [term, setTerm] = useState('1')
  const [academicContextReady, setAcademicContextReady] = useState(false)
  const [gradeId, setGradeId] = useState<number>()
  const [mode, setMode] = useState<GaokaoMode>('3+1+2')
  const [overview, setOverview] = useState<GaokaoOverview>()
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState('')
  const [generationOpen, setGenerationOpen] = useState(false)
  const [resultsOpen, setResultsOpen] = useState(false)
  const [capacity, setCapacity] = useState(40)
  const [generationPreview, setGenerationPreview] = useState<Awaited<ReturnType<typeof gaokaoApi.generateTeachingClasses>>>()
  const [replaceExisting, setReplaceExisting] = useState(false)
  const [reviewChoices, setReviewChoices] = useState<import('@/api').GaokaoChoiceReview[]>([])
  const [reviewingId, setReviewingId] = useState<number>()
  const [selectedReviewIds, setSelectedReviewIds] = useState<number[]>([])

  const isWalkClass = mode !== 'traditional'
  const userRoles = user?.roles || (user?.role ? [user.role] : [])
  const canReviewChoices = userRoles.includes('head_teacher')
  const workflow = overview?.workflow

  const load = async () => {
    setLoading(true)
    try {
      const data = await gaokaoApi.overview({
        academic_year: academicYear,
        term,
        grade_id: gradeId,
      })
      setOverview(data)
      setGradeId((prev) => prev ?? data.grades[0]?.id)
      const reviews = canReviewChoices
        ? await gaokaoApi.choicesForReview({
            academic_year: academicYear,
            term,
            grade_id: gradeId,
            status_filter: 'confirmed',
          }).catch(() => [])
        : []
      setReviewChoices(reviews)
      setSelectedReviewIds([])
    } catch (e) {
      message.error(e instanceof Error ? e.message : '选科数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    authApi
      .menus()
      .then((menu) => setMode((menu.gaokao_mode as GaokaoMode) || '3+1+2'))
      .catch(() => setMode('3+1+2'))
    authApi.academicYears().then((settings) => {
      if (settings.current_academic_year) setAcademicYear(settings.current_academic_year)
      if (settings.current_term) setTerm(settings.current_term)
    }).catch(() => undefined).finally(() => setAcademicContextReady(true))
  }, [])

  useEffect(() => {
    if (!academicContextReady) return
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [academicContextReady, academicYear, term, canReviewChoices])

  // 年级变化时重新拉取（gradeId 首次由 overview 回填后再触发一次）
  useEffect(() => {
    if (overview && gradeId !== undefined) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gradeId])

  useEffect(() => {
    setGenerationOpen(false); setGenerationPreview(undefined); setReplaceExisting(false)
    setResultsOpen(false)
  }, [gradeId, academicYear, term])

  const generateClasses = async (preview: boolean) => {
    if (!gradeId) {
      message.warning('请选择年级')
      return
    }
    setGenerating('classes')
    try {
      const result = await gaokaoApi.generateTeachingClasses({
        grade_id: gradeId,
        academic_year: academicYear,
        term,
        capacity,
        preview,
        replace_existing: replaceExisting,
        preview_token: preview ? undefined : generationPreview?.preview_token,
      })
      if (preview) {
        setGenerationPreview(result)
        setReplaceExisting(false)
        return
      }
      setGenerationOpen(false)
      setGenerationPreview(undefined)
      message.success(`已生成 ${result.created} 个教学班，学生将在联合排课时分入`)
      await load()
      setResultsOpen(true)
    } catch (e) {
      setGenerationPreview(undefined)
      message.error(e instanceof Error ? e.message : '教学班生成失败')
    } finally {
      setGenerating('')
    }
  }

  const reviewChoice = async (choiceId: number, action: 'approve' | 'reject') => {
    setReviewingId(choiceId)
    try {
      await gaokaoApi.reviewChoice(choiceId, action)
      setReviewChoices((items) => items.filter((item) => item.id !== choiceId))
      message.success(action === 'approve' ? '选科已审核通过并锁定' : '选科已驳回，学生可重新提交')
    } catch (e) {
      message.error(e instanceof Error ? e.message : '选科审核失败')
    } finally {
      setReviewingId(undefined)
    }
  }

  const batchApproveChoices = async () => {
    if (!selectedReviewIds.length) return
    setGenerating('review-batch')
    try {
      const result = await gaokaoApi.batchApproveChoices(selectedReviewIds)
      setReviewChoices((items) => items.filter((item) => !selectedReviewIds.includes(item.id)))
      setSelectedReviewIds([])
      message.success(`已批量通过 ${result.updated} 人${result.skipped ? `，跳过 ${result.skipped} 人` : ''}`)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '批量审核失败')
    } finally {
      setGenerating('')
    }
  }

  const stats = useMemo(
    () => ({
      students: overview?.stats.student_count ?? 0,
      confirmed: overview?.stats.confirmed_count ?? 0,
      coverage: overview?.stats.coverage_rate ?? 0,
      teaching: overview?.stats.teaching_class_count ?? 0,
      combos: overview?.stats.combination_count ?? 0,
    }),
    [overview],
  )

  return (
    <div className="gk-page gk-workbench">
      <PageHeader
        title={canReviewChoices ? '班级选科审核' : '选科与分班'}
        extra={
          isWalkClass && !canReviewChoices ? (
            <>
              <Button disabled={!gradeId} onClick={() => setResultsOpen(true)}>查看教学班结果</Button>
              <Dropdown trigger={['click']} menu={{ items: [{ key: 'classes', label: '只生成教学班（暂不分学生）',
                disabled: !workflow?.can_generate_teaching_classes || Boolean(generating),
                onClick: () => { setGenerationPreview(undefined); setReplaceExisting(false); setGenerationOpen(true) },
              }] }}><Button>教学班生成</Button></Dropdown>
              <Button type="primary" disabled={!gradeId || !academicContextReady}
                onClick={() => navigate(`/scheduling?tab=hours&grade=${gradeId}`)}>去排课管理</Button>
            </>
          ) : undefined
        }
      />
      {resultsOpen && gradeId && <TeachingClassResults gradeId={gradeId} academicYear={academicYear} term={term}
        gradeName={overview?.grades.find((grade) => grade.id === gradeId)?.name} onClose={() => setResultsOpen(false)} />}
      <Modal title="教学班生成" open={generationOpen} width={820}
        onCancel={() => { if (generating !== 'classes') setGenerationOpen(false) }} footer={<Space>
          <Button disabled={generating === 'classes'} onClick={() => setGenerationOpen(false)}>取消</Button>
          <Button loading={generating === 'classes'} onClick={() => void generateClasses(true)}>预览方案</Button>
          <Button type="primary" loading={generating === 'classes'} disabled={!generationPreview?.preview_token || Boolean(generationPreview.existing_class_count && !replaceExisting)}
            onClick={() => void generateClasses(false)}>生成教学班</Button>
        </Space>}>
        <p>{academicYear} · 第 {term} 学期 · {overview?.grades.find((grade) => grade.id === gradeId)?.name}</p>
        <Space>每班人数上限<InputNumber aria-label="教学班人数上限" min={20} max={60} precision={0} value={capacity} disabled={generating === 'classes'}
          onChange={(value) => { setCapacity(value ?? 40); setGenerationPreview(undefined); setReplaceExisting(false) }} />人</Space>
        <p>按已确认选科人数和班额创建教学班，人数均衡；此步骤不分配学生。学生分班和课表将在联合排课时确定并保存。</p>
        {generationPreview && <>
          <Alert type="info" showIcon message={`计划生成 ${generationPreview.created} 个教学班；本学期可用共享教室 ${generationPreview.available_room_count ?? 0} 间。教室按需使用，不要求全部用满。`} />
          {generationPreview.warnings?.map((warning) => <Alert key={warning} type="warning" showIcon message={warning} style={{ marginTop: 8 }} />)}
          <Table rowKey={(row) => `${row.subject_id}-${row.sequence}`} size="small" style={{ marginTop: 12 }} dataSource={generationPreview.classes} pagination={{ pageSize: 8 }} columns={[
            { title: '科目', dataIndex: 'subject_name' }, { title: '教学班序号', dataIndex: 'sequence' },
            { title: '预计人数', dataIndex: 'student_count' }, { title: '每周课时', dataIndex: 'weekly_periods' },
          ]} />
          {Boolean(generationPreview.existing_class_count) && <>
            <Alert type="warning" showIcon message={`已有 ${generationPreview.existing_class_count} 个教学班。替换会删除原班成员、教师和教室安排及已有走班课表，单班课时调整不会保留。`} />
            <Checkbox checked={replaceExisting} disabled={generating === 'classes'} onChange={(event) => setReplaceExisting(event.target.checked)} style={{ marginTop: 12 }}>我确认替换本年级本学期已有教学班</Checkbox>
          </>}
        </>}
      </Modal>
      <div className="gk-contextbar">
        <div className="gk-context-copy">
          <span className="gk-kicker">ACADEMIC PLANNING / {academicYear}</span>
          <strong>{MODE_TITLE[mode]}</strong>
        </div>
        <div className="gk-context-controls">
          <div className="gk-field">
            <span>当前年级</span>
          <Select
            value={gradeId}
            onChange={setGradeId}
            popupMatchSelectWidth={false}
            placeholder="选择年级"
            options={(overview?.grades ?? []).map((g) => ({ label: g.name, value: g.id }))}
          />
          </div>
          <span className="gk-scheme-chip"><ReadOutlined /> {overview?.scheme?.name || '尚未建立届别方案'}</span>
        </div>
      </div>

      {isWalkClass && !canReviewChoices && (
        <section className="gk-workflow" aria-label="选科实施流程">
          <div className="gk-workflow-head">
            <div className="gk-stage-title">
              <span className="gk-stage-icon"><ThunderboltFilled /></span>
              <div>
              <span>当前阶段</span>
              <strong>{workflow?.label || '等待年级数据'}</strong>
              </div>
            </div>
            <div className="gk-stage-description">
              <ClockCircleOutlined />
              <p>{workflow?.description || '选择年级和学期后判断选科所处阶段。'}</p>
            </div>
          </div>
          <div className="gk-workflow-track">
            {WORKFLOW_STEPS.map((step, index) => {
              const activeIndex = WORKFLOW_STEPS.findIndex((item) => item.code === workflow?.code)
              const state = activeIndex < 0 ? 'pending' : index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending'
              return (
                <div key={step.code} className={`gk-workflow-step is-${state}`}>
                  <i aria-hidden="true" />
                  <div><strong>{step.label}</strong><span>{step.note}</span></div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {overview?.workflow_warnings?.length ? (
        <Alert
          className="gk-workflow-warning"
          type="warning"
          showIcon
          message="选科流程与存量数据不一致"
          description={overview.workflow_warnings.map((warning) => <div key={warning}>{warning}</div>)}
        />
      ) : null}

      <div className="gk-metrics">
        <div className="gk-metric metric-blue">
          <span className="gk-metric-icon"><TeamOutlined /></span>
          <div><span>年级学生</span><strong>{stats.students}</strong><small>全部在籍学生</small></div>
        </div>
        <div className="gk-metric metric-green">
          <span className="gk-metric-icon"><CheckCircleFilled /></span>
          <div><span>{isWalkClass ? '已确认选科' : '已确认分科'}</span><strong>{stats.confirmed}</strong><small>等待审核或已锁定</small></div>
        </div>
        <div className="gk-metric metric-orange">
          <span className="gk-metric-icon"><ApartmentOutlined /></span>
          <div><span>确认覆盖率</span><strong>{stats.coverage}%</strong><small className="gk-progress"><i style={{ width: `${Math.min(stats.coverage, 100)}%` }} /></small></div>
        </div>
        <div className="gk-metric metric-purple">
          <span className="gk-metric-icon"><ReadOutlined /></span>
          <div><span>{isWalkClass ? '已生成教学班' : '科类组合'}</span><strong>{isWalkClass ? stats.teaching : stats.combos}</strong><small>{isWalkClass ? '课表在排课管理生成' : '按当前模式统计'}</small></div>
        </div>
      </div>

      {canReviewChoices && <Card
        className="gk-card gk-review-card"
        title={<div className="gk-card-title"><span>班级选科审核</span><Tag color={reviewChoices.length ? 'orange' : 'default'}>待审 {reviewChoices.length} 人</Tag></div>}
        style={{ marginBottom: 18 }}
        extra={
          <Space>
            <Popconfirm title={`确认通过选中的 ${selectedReviewIds.length} 人？`} onConfirm={() => void batchApproveChoices()} okText="通过并锁定" cancelText="取消">
              <Button type="primary" size="small" disabled={!selectedReviewIds.length} loading={generating === 'review-batch'}>
                批量通过并锁定
              </Button>
            </Popconfirm>
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={reviewChoices}
          rowSelection={{ selectedRowKeys: selectedReviewIds, onChange: (keys) => setSelectedReviewIds(keys as number[]) }}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          locale={{ emptyText: '暂无待审核的学生选科' }}
          columns={[
            { title: '学生', key: 'student', render: (_: unknown, row: import('@/api').GaokaoChoiceReview) => `${row.student_name}（${row.student_no}）` },
            { title: '首选', dataIndex: 'primary_subject_name', width: 100 },
            { title: '再选', dataIndex: 'secondary_subject_names', width: 180, render: (names: string[]) => names.join('、') },
            { title: '轮次', dataIndex: 'round_no', width: 70 },
            {
              title: '操作',
              width: 180,
              render: (_: unknown, row: import('@/api').GaokaoChoiceReview) => (
                <span>
                  <Popconfirm title="确认通过并锁定该学生选科？" onConfirm={() => void reviewChoice(row.id, 'approve')} okText="通过" cancelText="取消">
                  <Button type="link" size="small" loading={reviewingId === row.id}>通过并锁定</Button>
                  </Popconfirm>
                  <Popconfirm title="确认驳回该学生选科？" onConfirm={() => void reviewChoice(row.id, 'reject')} okText="驳回" cancelText="取消">
                    <Button type="link" danger size="small" disabled={reviewingId === row.id}>驳回</Button>
                  </Popconfirm>
                </span>
              ),
            },
          ]}
        />
      </Card>}

      <div className="gk-grid">
        <Card
          className="gk-card gk-combination-card"
          title={<div className="gk-card-title"><span>{isWalkClass ? '选科组合分布' : '文理分科分布'}</span></div>}
          styles={{ body: { padding: 0 } }}
        >
          <Table
            rowKey={(row) => `${row.key}-${row.label}`}
            dataSource={overview?.combinations ?? []}
            loading={loading}
            pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 条` }}
            size="middle"
            scroll={{ y: 320 }}
            locale={{
              emptyText: (
                <EmptyState icon="users" title="暂无分布数据" desc="确认选科后展示" height={240} />
              ),
            }}
            columns={[
              { title: '组合', dataIndex: 'label', key: 'label', width: 280 },
              {
                title: '人数',
                dataIndex: 'count',
                key: 'count',
                width: 100,
                render: (v?: number) => <b className="gk-num">{v ?? 0}</b>,
              },
            ]}
          />
        </Card>

        {isWalkClass ? (
          <Card
            className="gk-card gk-demand-card"
            title={<div className="gk-card-title"><span>学科资源需求</span></div>}
            styles={{ body: { padding: 0 } }}
          >
            <Table
              rowKey="subject_id"
              dataSource={overview?.subject_demand ?? []}
              loading={loading}
              pagination={{ pageSize: 10, showSizeChanger: false, showTotal: (total) => `共 ${total} 条` }}
              size="middle"
              scroll={{ y: 320 }}
              locale={{
                emptyText: (
                  <EmptyState
                    icon="file-text"
                    title="暂无学科需求"
                    desc="生成教学班后展示"
                    height={240}
                  />
                ),
              }}
              columns={[
                { title: '学科', dataIndex: 'subject_name', key: 'subject_name', width: 120 },
                {
                  title: '授课轨道',
                  dataIndex: 'delivery_mode',
                  key: 'delivery_mode',
                  width: 110,
                  render: (value: string) => (
                    <Tag color={value === 'teaching_class' ? 'blue' : 'default'}>
                      {value === 'teaching_class' ? '教学班走班' : '行政班授课'}
                    </Tag>
                  ),
                },
                {
                  title: '学生数',
                  dataIndex: 'student_count',
                  key: 'student_count',
                  width: 80,
                  align: 'right' as const,
                },
                {
                  title: '建议班数',
                  dataIndex: 'recommended_class_count',
                  key: 'recommended_class_count',
                  width: 100,
                  align: 'right' as const,
                },
                {
                  title: '教师',
                  dataIndex: 'teacher_count',
                  key: 'teacher_count',
                  width: 80,
                  align: 'right' as const,
                },
              ]}
            />
          </Card>
        ) : (
          <Card className="gk-card gk-note-card">
            <div className="gk-note">
              <Tag color="default" style={{ marginInlineEnd: 8 }}>
                行政班教学
              </Tag>
              <p>传统文理模式保留行政班排课，不开放走班教学班和走班课表功能。</p>
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
