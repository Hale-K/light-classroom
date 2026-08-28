import { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Card, Select, Table, Tag } from 'antd'
import { authApi, gaokaoApi } from '@/api'
import type { GaokaoOverview } from '@/api'
import PageHeader from '@/components/PageHeader'
import EmptyState from '@/components/EmptyState'
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

  const [academicYear, setAcademicYear] = useState('2026-2027')
  const [term, setTerm] = useState('1')
  const [gradeId, setGradeId] = useState<number>()
  const [mode, setMode] = useState<GaokaoMode>('3+1+2')
  const [overview, setOverview] = useState<GaokaoOverview>()
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState('')

  const isWalkClass = mode !== 'traditional'
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
    }).catch(() => undefined)
  }, [])

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [academicYear, term])

  // 年级变化时重新拉取（gradeId 首次由 overview 回填后再触发一次）
  useEffect(() => {
    if (overview && gradeId !== undefined) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gradeId])

  const generateClasses = async () => {
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
        capacity: 40,
      })
      message.success(`已生成 ${result.created} 个教学班`)
      await load()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '教学班生成失败')
    } finally {
      setGenerating('')
    }
  }

  const generateSchedule = async () => {
    if (!gradeId) {
      message.warning('请选择年级')
      return
    }
    setGenerating('schedule')
    try {
      const result = await gaokaoApi.generateSchedule({
        grade_id: gradeId,
        academic_year: academicYear,
        term,
      })
      message.success(`已生成 ${result.created} 个走班课时`)
      await load()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '走班课表生成失败')
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
    <div className="gk-page">
      <PageHeader
        title={MODE_TITLE[mode]}
        extra={
          isWalkClass ? (
            <>
              <Button
                loading={generating === 'classes'}
                disabled={workflow ? !workflow.can_generate_teaching_classes : true}
                title={workflow?.description}
                onClick={generateClasses}
              >
                生成教学班
              </Button>
              <Button
                type="primary"
                loading={generating === 'schedule'}
                disabled={workflow ? !workflow.can_generate_schedule : true}
                title={workflow?.description}
                onClick={generateSchedule}
              >
                生成走班课表
              </Button>
            </>
          ) : undefined
        }
      />
      <div className="gk-filters">
        <div className="gk-field">
          <span>年级</span>
          <Select
            value={gradeId}
            onChange={setGradeId}
            popupMatchSelectWidth={false}
            placeholder="选择年级"
            options={(overview?.grades ?? []).map((g) => ({ label: g.name, value: g.id }))}
          />
        </div>
        <span className="gk-chip">{overview?.scheme?.name || '尚未建立届别方案'}</span>
      </div>

      {isWalkClass && (
        <section className="gk-workflow" aria-label="选科实施流程">
          <div className="gk-workflow-head">
            <div>
              <span>当前阶段</span>
              <strong>{workflow?.label || '等待年级数据'}</strong>
            </div>
            <p>{workflow?.description || '选择年级和学期后判断选科所处阶段。'}</p>
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
        <div>
          <span>年级学生</span>
          <strong>{stats.students}</strong>
        </div>
        <div>
          <span>{isWalkClass ? '已确认选科' : '已确认分科'}</span>
          <strong>{stats.confirmed}</strong>
        </div>
        <div>
          <span>确认覆盖率</span>
          <strong>{stats.coverage}%</strong>
        </div>
        <div>
          <span>{isWalkClass ? '教学班' : '科类'}</span>
          <strong>{isWalkClass ? stats.teaching : stats.combos}</strong>
        </div>
      </div>

      <div className="gk-grid">
        <Card
          className="gk-card"
          title={isWalkClass ? '选科组合分布' : '文理分科分布'}
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
              { title: '组合', dataIndex: 'label', key: 'label' },
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
            className="gk-card"
            title="学科资源需求"
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
                { title: '学科', dataIndex: 'subject_name', key: 'subject_name' },
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
                  title: '走班学生',
                  dataIndex: 'walk_student_count',
                  key: 'walk_student_count',
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
