import { useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Divider,
  Drawer,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Select,
  Spin,
  Tag,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import { examApi, orgApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import DictTag from '@/components/DictTag'
import Icon from '@/components/Icon'
import { DIFFICULTY_DICT, EXAM_TYPE_DICT, PAPER_STATUS_DICT } from '@/types/dict'
import type { Exam, Grade, Paper, Question } from '@/types'
import PaperLibrary, { PAPER_SUBJECTS } from './PaperLibrary'

/** 学科演示映射：真实系统可有 subject 表；此处以固定 id 对应常见科目 */
const SUBJECTS = PAPER_SUBJECTS

interface DraftQuestion {
  score: number
  difficulty: string
  content: string
}

export default function ExamManage() {
  const { message, modal } = App.useApp()
  const navigate = useNavigate()

  const [loading, setLoading] = useState(false)
  const [exams, setExams] = useState<Exam[]>([])
  const [papersByExam, setPapersByExam] = useState<Record<number, Paper[]>>({})
  const [filter, setFilter] = useState('')
  const [grades, setGrades] = useState<Grade[]>([])

  // 新建考试
  const [examDlg, setExamDlg] = useState(false)
  const [examSaving, setExamSaving] = useState(false)
  const [examForm, setExamForm] = useState({ name: '', exam_type: 'monthly', academic_year: '' })

  // 从书架抽出的试卷
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerExam, setDrawerExam] = useState<Exam | null>(null)
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const [drawerLoading, setDrawerLoading] = useState(false)

  // 轻量建卷
  const [paperDlg, setPaperDlg] = useState(false)
  const [paperSaving, setPaperSaving] = useState(false)
  const [paperExamId, setPaperExamId] = useState(0)
  const [paperForm, setPaperForm] = useState({ title: '', subject_id: 2, grade_id: 0, total_score: 100 })
  const [editingPaper, setEditingPaper] = useState<Paper | null>(null)
  const [newQ, setNewQ] = useState({ score: 0, difficulty: 'basic', content: '' })
  const [draftQuestions, setDraftQuestions] = useState<DraftQuestion[]>([])

  const filteredExams = useMemo(
    () => (filter ? exams.filter((e) => e.status === filter) : exams),
    [exams, filter],
  )

  const loadExams = async () => {
    setLoading(true)
    try {
      const list = await examApi.list()
      setExams(list)
      const details = await Promise.allSettled(list.map((exam) => examApi.detail(exam.id)))
      setPapersByExam(
        Object.fromEntries(
          list.map((exam, index) => [
            exam.id,
            details[index].status === 'fulfilled' ? details[index].value.papers || [] : [],
          ]),
        ),
      )
    } catch (e) {
      message.error(e instanceof Error ? e.message : '考试列表加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadExams()
    orgApi
      .grades()
      .then(setGrades)
      .catch((e) => message.error(e instanceof Error ? e.message : '年级加载失败'))
  }, [])

  // ---------- 新建考试 ----------
  const openExamDlg = () => {
    const now = new Date().getFullYear()
    setExamForm({ name: '', exam_type: 'monthly', academic_year: `${now}-${now + 1}` })
    setExamDlg(true)
  }

  const saveExam = async () => {
    if (!examForm.name.trim()) {
      message.warning('请输入考试名称')
      return
    }
    setExamSaving(true)
    try {
      await examApi.create({
        name: examForm.name.trim(),
        exam_type: examForm.exam_type,
        academic_year: examForm.academic_year,
      })
      message.success('考试已创建')
      setExamDlg(false)
      await loadExams()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '创建失败')
    } finally {
      setExamSaving(false)
    }
  }

  const changeStatus = async (exam: Exam, status: string) => {
    try {
      await examApi.updateStatus(exam.id, status)
      message.success('状态已更新')
      await loadExams()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '状态更新失败')
    }
  }

  // ---------- 从书架打开试卷 ----------
  const openPaper = async (paper: Paper, exam: Exam) => {
    setDrawerExam(exam)
    setSelectedPaper(paper)
    setDrawerOpen(true)
    setDrawerLoading(true)
    try {
      setSelectedPaper(await examApi.paper(paper.id))
    } catch (e) {
      message.error(e instanceof Error ? e.message : '试卷详情加载失败')
    } finally {
      setDrawerLoading(false)
    }
  }

  const reloadPapers = async () => {
    if (!drawerExam) return
    const detail = await examApi.detail(drawerExam.id)
    setPapersByExam((current) => ({ ...current, [drawerExam.id]: detail.papers || [] }))
  }

  // ---------- 新建 / 编辑试卷（轻量建卷） ----------
  const openNewPaper = async (exam: Exam, paper?: Paper) => {
    setPaperExamId(exam.id)
    setDrawerOpen(false)
    setDraftQuestions([])
    setPaperDlg(true)
    if (paper) {
      setPaperForm({
        title: paper.title,
        subject_id: paper.subject_id || 2,
        grade_id: paper.grade_id || grades[0]?.id || 0,
        total_score: paper.total_score || 100,
      })
      const fresh = await examApi.paper(paper.id)
      setEditingPaper(fresh)
    } else {
      setEditingPaper(null)
      setPaperForm({
        title: `${exam.name} 试卷`,
        subject_id: 2,
        grade_id: grades[0]?.id || 0,
        total_score: 100,
      })
    }
  }

  const addDraft = () => {
    setDraftQuestions((prev) => [...prev, { ...newQ }])
    setNewQ({ score: 0, difficulty: 'basic', content: '' })
  }

  const removeDraft = (i: number) => {
    setDraftQuestions((prev) => prev.filter((_, idx) => idx !== i))
  }

  const savePaper = async () => {
    setPaperSaving(true)
    try {
      let paper: Paper
      if (editingPaper) {
        paper = editingPaper
      } else {
        paper = await examApi.createPaper(paperExamId, {
          title: paperForm.title,
          subject_id: paperForm.subject_id,
          grade_id: paperForm.grade_id,
          total_score: paperForm.total_score,
        })
        setEditingPaper(paper)
        message.success('试卷已创建，可继续添加题目')
      }
      // 提交草稿题目
      for (const q of draftQuestions) {
        await examApi.addQuestion(paper.id, {
          score: q.score,
          difficulty: q.difficulty,
          content: q.content || null,
        })
      }
      setDraftQuestions([])
      message.success(`已保存 ${paper.id} 号题`)
      // 重新拉取题目
      const fresh = await examApi.paper(paper.id)
      setEditingPaper(fresh)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setPaperSaving(false)
    }
  }

  const finalizePaper = () => {
    if (!editingPaper) return
    modal.confirm({
      title: '定稿确认',
      content: '定稿后试卷不可再增改题目，确定定稿吗？',
      okText: '定稿',
      cancelText: '取消',
      onOk: async () => {
        try {
          await examApi.finalizePaper(editingPaper.id)
          message.success('试卷已定稿')
          setPaperDlg(false)
          setDrawerOpen(true)
          await reloadPapers()
        } catch (e) {
          message.error(e instanceof Error ? e.message : '定稿失败')
        }
      },
    })
  }

  const goGrading = (p: Paper) => navigate(`/grading/${p.id}`)
  const goStats = (p: Paper) => navigate(`/stats/${p.id}`)

  return (
    <div className="zh-page">
      <PageHeader
        title="试卷库"
        extra={
          <Button type="primary" icon={<Icon name="calendar" size={16} />} onClick={openExamDlg}>
            新建考试
          </Button>
        }
      />

      <div className="zh-library-exam-filter">
        <span>按考试阶段</span>
        <Radio.Group
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          size="small"
          optionType="button"
        >
          <Radio.Button value="">全部</Radio.Button>
          <Radio.Button value="preparing">筹备中</Radio.Button>
          <Radio.Button value="ongoing">进行中</Radio.Button>
          <Radio.Button value="ended">已结束</Radio.Button>
        </Radio.Group>
      </div>
      <PaperLibrary
        exams={filteredExams}
        papersByExam={papersByExam}
        loading={loading}
        onOpenPaper={openPaper}
        onCreatePaper={openNewPaper}
        onCreateExam={openExamDlg}
        grades={grades}
      />

      {/* 新建考试 */}
      <Modal
        title="新建考试"
        open={examDlg}
        onCancel={() => setExamDlg(false)}
        onOk={saveExam}
        okText="创建"
        cancelText="取消"
        confirmLoading={examSaving}
        okButtonProps={{ disabled: !examForm.name.trim() }}
        width={440}
      >
        <Form layout="vertical">
          <Form.Item label="考试名称" required>
            <Input
              value={examForm.name}
              onChange={(e) => setExamForm((prev) => ({ ...prev, name: e.target.value }))}
              placeholder="如：高三月考（一）"
              maxLength={100}
            />
          </Form.Item>
          <Form.Item label="考试类型">
            <Select
              value={examForm.exam_type}
              onChange={(v) => setExamForm((prev) => ({ ...prev, exam_type: v }))}
              options={Object.entries(EXAM_TYPE_DICT).map(([value, item]) => ({
                label: item.label,
                value,
              }))}
            />
          </Form.Item>
          <Form.Item label="学年">
            <Input
              value={examForm.academic_year}
              onChange={(e) => setExamForm((prev) => ({ ...prev, academic_year: e.target.value }))}
              placeholder="如：2026-2027"
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* 从书架抽出的试卷详情 */}
      <Drawer
        title={selectedPaper ? `正在阅读 · ${selectedPaper.title}` : '试卷详情'}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setSelectedPaper(null)
        }}
        width="100%"
        placement="right"
        rootClassName="zh-paper-reader-drawer"
        destroyOnHidden
      >
        {drawerLoading ? (
          <div className="zh-drawer-loading">
            <Spin />
          </div>
        ) : selectedPaper ? (
          <div className="zh-open-paper">
            <section className="zh-open-paper-cover">
              <span>{SUBJECTS.find((subject) => subject.id === selectedPaper.subject_id)?.name || '综合'}试卷</span>
              <h2>{selectedPaper.title}</h2>
              <p>{drawerExam?.academic_year || '校本试卷库'}</p>
              <div className="zh-open-paper-seal">轻课堂<br />教务</div>
            </section>
            <section className="zh-open-paper-page">
              <div className="zh-open-paper-heading">
                <div>
                  <span className="zh-library-kicker">PAPER RECORD</span>
                  <h3>{selectedPaper.title}</h3>
                </div>
                <DictTag dict={PAPER_STATUS_DICT} value={selectedPaper.status} />
              </div>
              <dl className="zh-open-paper-meta">
                <div><dt>所属考试</dt><dd>{drawerExam?.name || '—'}</dd></div>
                <div><dt>学科</dt><dd>{SUBJECTS.find((subject) => subject.id === selectedPaper.subject_id)?.name || '—'}</dd></div>
                <div><dt>满分</dt><dd>{selectedPaper.total_score ?? 0} 分</dd></div>
                <div><dt>题目</dt><dd>{selectedPaper.questions?.length ?? 0} 题</dd></div>
              </dl>
              <div className="zh-open-paper-questions">
                <div className="zh-open-paper-section-title">题目目录</div>
                {selectedPaper.questions?.length ? selectedPaper.questions.slice(0, 6).map((question) => (
                  <div key={question.id} className="zh-open-paper-question">
                    <span>{String(question.question_no).padStart(2, '0')}</span>
                    <p>{question.content || '未填写题干'}</p>
                    <b>{question.score} 分</b>
                  </div>
                )) : <p className="zh-open-paper-muted">暂无题目，继续建卷后会在这里形成目录。</p>}
              </div>
              <div className="zh-open-paper-actions">
                {selectedPaper.status === 'finalized' ? (
                  <>
                    <Button type="primary" onClick={() => goGrading(selectedPaper)}>进入打分</Button>
                    <Button onClick={() => goStats(selectedPaper)}>查看成绩</Button>
                  </>
                ) : (
                  <Button type="primary" onClick={() => drawerExam && openNewPaper(drawerExam, selectedPaper)}>
                    继续建卷
                  </Button>
                )}
                {drawerExam && (
                  <Dropdown
                    trigger={['click']}
                    menu={{
                      items: [
                        { key: 'ongoing', label: '考试设为进行中' },
                        { key: 'ended', label: '考试设为已结束' },
                        { key: 'archived', label: '归档考试' },
                      ],
                      onClick: ({ key }) => changeStatus(drawerExam, key),
                    }}
                  >
                    <Button type="text">更新考试状态</Button>
                  </Dropdown>
                )}
              </div>
            </section>
          </div>
        ) : null}
      </Drawer>

      {/* 轻量建卷 */}
      <Modal
        title="轻量建卷"
        open={paperDlg}
        onCancel={() => {
          setPaperDlg(false)
          setDraftQuestions([])
        }}
        width={640}
        footer={[
          <Button
            key="close"
            onClick={() => {
              setPaperDlg(false)
              setDraftQuestions([])
            }}
          >
            关闭
          </Button>,
          <Button key="save" loading={paperSaving} onClick={savePaper}>
            保存题目
          </Button>,
          editingPaper ? (
            <Button key="finalize" type="primary" onClick={finalizePaper}>
              定稿
            </Button>
          ) : null,
        ]}
      >
        <Form layout="vertical">
          <Form.Item label="试卷标题" required>
            <Input
              value={paperForm.title}
              onChange={(e) => setPaperForm((prev) => ({ ...prev, title: e.target.value }))}
              maxLength={200}
            />
          </Form.Item>
          <div className="zh-form-row3">
            <Form.Item label="科目">
              <Select
                value={paperForm.subject_id}
                onChange={(v) => setPaperForm((prev) => ({ ...prev, subject_id: v }))}
                options={SUBJECTS.map((s) => ({ label: s.name, value: s.id }))}
              />
            </Form.Item>
            <Form.Item label="年级">
              <Select
                value={paperForm.grade_id}
                onChange={(v) => setPaperForm((prev) => ({ ...prev, grade_id: v }))}
                placeholder="选择年级"
                options={grades.map((g) => ({ label: g.name, value: g.id }))}
              />
            </Form.Item>
            <Form.Item label="满分">
              <InputNumber
                value={paperForm.total_score}
                onChange={(v) => setPaperForm((prev) => ({ ...prev, total_score: v ?? 100 }))}
                min={1}
                max={200}
                style={{ width: '100%' }}
              />
            </Form.Item>
          </div>
        </Form>

        <Divider orientation="left" style={{ margin: '4px 0 16px' }}>
          题目清单
        </Divider>
        <div className="zh-question-editor">
          {editingPaper?.questions?.length ? (
            <div className="zh-q-list">
              {editingPaper.questions.map((q: Question) => (
                <div key={q.id} className="zh-q-row">
                  <span className="zh-q-no">{q.question_no}</span>
                  <DictTag dict={DIFFICULTY_DICT} value={q.difficulty} />
                  <span className="zh-q-content">{q.content || '（无题干）'}</span>
                  <span className="zh-q-score">{q.score} 分</span>
                </div>
              ))}
            </div>
          ) : null}
          <div className="zh-q-add">
            <span className="zh-q-desc">新增题目（默认自动续号）</span>
            <div className="zh-q-add-row">
              <InputNumber
                value={newQ.score}
                onChange={(v) => setNewQ((prev) => ({ ...prev, score: v ?? 0 }))}
                min={0}
                max={200}
                placeholder="分值"
                style={{ width: 120 }}
              />
              <Select
                value={newQ.difficulty}
                onChange={(v) => setNewQ((prev) => ({ ...prev, difficulty: v }))}
                style={{ width: 100 }}
                options={Object.entries(DIFFICULTY_DICT).map(([value, item]) => ({
                  label: item.label,
                  value,
                }))}
              />
              <Input
                value={newQ.content}
                onChange={(e) => setNewQ((prev) => ({ ...prev, content: e.target.value }))}
                placeholder="题干/知识点要点（可选）"
                allowClear
              />
              <Button onClick={addDraft}>添加</Button>
            </div>
            {draftQuestions.map((q, i) => (
              <div key={i} className="zh-q-row zh-q-draft">
                <Tag color="orange" style={{ marginInlineEnd: 0 }}>
                  草稿
                </Tag>
                <span className="zh-q-content">{q.content || '（无题干）'}</span>
                <span className="zh-q-score">{q.score} 分</span>
                <Button type="link" danger size="small" onClick={() => removeDraft(i)}>
                  移除
                </Button>
              </div>
            ))}
          </div>
        </div>
      </Modal>
    </div>
  )
}
