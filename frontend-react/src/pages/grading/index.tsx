import { useEffect, useMemo, useState } from 'react'
import { App, Button, InputNumber, Spin } from 'antd'
import { useParams } from 'react-router-dom'
import { gradingApi } from '@/api'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import type { Submission, SubmissionDetail } from '@/types'

export default function GradingWorkbench() {
  const { message, modal } = App.useApp()
  const params = useParams<{ paperId: string }>()
  const paperId = Number(params.paperId)

  const [loading, setLoading] = useState(true)
  const [submissions, setSubmissions] = useState<Submission[]>([])
  const [currentIdx, setCurrentIdx] = useState(0)
  const [detail, setDetail] = useState<SubmissionDetail | null>(null)
  const [scores, setScores] = useState<Record<number, number | null>>({})

  const currentSub = submissions[currentIdx]
  const gradedCount = submissions.filter((s) => s.status === 'graded').length
  const totalScore = useMemo(
    () =>
      (detail?.questions ?? []).reduce(
        (sum, q) => sum + (Number(scores[q.question_id]) || 0),
        0,
      ),
    [detail, scores],
  )
  const answeredCount = (detail?.questions ?? []).filter(
    (q) => scores[q.question_id] != null,
  ).length

  const loadDetail = async (idx: number, list?: Submission[]) => {
    const source = list ?? submissions
    const sub = source[idx]
    if (!sub) {
      setDetail(null)
      setScores({})
      return
    }
    setLoading(true)
    try {
      const d = await gradingApi.detail(sub.id)
      setDetail(d)
      const s: Record<number, number | null> = {}
      d.questions.forEach((q) => {
        s[q.question_id] = q.given_score
      })
      setScores(s)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '批阅详情加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadQueue = async () => {
    setLoading(true)
    try {
      const list = await gradingApi.queue(paperId)
      setSubmissions(list)
      const nextIdx = list.findIndex((s) => s.status !== 'graded')
      const idx = nextIdx >= 0 ? nextIdx : 0
      setCurrentIdx(idx)
      await loadDetail(idx, list)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '队列加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadQueue()
  }, [])

  const jumpTo = (i: number) => {
    if (i < 0 || i >= submissions.length) return
    setCurrentIdx(i)
    void loadDetail(i)
  }

  const saveScore = async (qid: number, val: number) => {
    if (!currentSub) return
    try {
      await gradingApi.score(currentSub.id, qid, val)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '分数保存失败')
    }
  }

  const nextQuestion = () => {
    const input = document.querySelector<HTMLElement>('.zh-grading .ant-input-number-input')
    if (input) input.focus()
  }

  const submitAndNext = () => {
    const sub = currentSub
    if (!sub) return
    modal.confirm({
      title: '提交本份',
      content: `是否提交「${detail?.student_name || `#${sub.id}`}」并汇总总分（当前 ${answeredCount}/${detail?.questions.length ?? 0} 题 / ${totalScore} 分）？`,
      okText: '提交',
      cancelText: '继续批改',
      onOk: async () => {
        try {
          await gradingApi.finalize(sub.id)
          await loadQueue()
          message.success('已提交下一份')
        } catch (e) {
          message.error(e instanceof Error ? e.message : '提交失败')
        }
      },
    })
  }

  // 键盘流：Enter 满分配下一未答题；[/] 或 上/下 切换学生
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 避免与输入框内打字冲突
      const tag = (e.target as HTMLElement)?.tagName
      if (
        (tag === 'INPUT' || tag === 'TEXTAREA') &&
        e.key !== 'Enter' &&
        e.key !== 'ArrowUp' &&
        e.key !== 'ArrowDown'
      ) {
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        const questions = detail?.questions ?? []
        const nextUnanswered = questions.find((q) => scores[q.question_id] == null)
        if (nextUnanswered) {
          const qid = nextUnanswered.question_id
          setScores((prev) => ({ ...prev, [qid]: nextUnanswered.score }))
          void saveScore(qid, nextUnanswered.score)
          message.success(`第 ${nextUnanswered.question_no} 题 满分`, 0.8)
        } else {
          nextQuestion()
        }
      }
      if (e.key === 'ArrowDown' || e.key === ']') jumpTo(currentIdx + 1)
      if (e.key === 'ArrowUp' || e.key === '[') jumpTo(currentIdx - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [detail, scores, submissions, currentIdx])

  if (loading && !submissions.length) {
    return (
      <div className="zh-grading">
        <div className="zh-empty-wrap">
          <Spin size="large" />
        </div>
      </div>
    )
  }

  return (
    <div className="zh-grading">
      {/* 工具条 */}
      <div className="zh-gbar">
        <div className="zh-gbar-left">
          <span className="zh-gfile">
            <Icon name="keyboard" size={16} /> 打分工作台
          </span>
          <span className="zh-gsep" />
          <span className="zh-gmeta">试卷 #{paperId}</span>
          <span className="zh-gmeta">
            已批 {gradedCount}/{submissions.length}
          </span>
        </div>
        <div className="zh-gbar-right">
          <Button size="small" type="text" onClick={() => jumpTo(currentIdx - 1)} disabled={currentIdx <= 0}>
            上一份
          </Button>
          <span className="zh-gidx">
            {currentIdx + 1}/{submissions.length}
          </span>
          <Button
            size="small"
            type="text"
            onClick={() => jumpTo(currentIdx + 1)}
            disabled={currentIdx >= submissions.length - 1}
          >
            下一份
          </Button>
          <Button size="small" type="primary" disabled={!detail?.submission} onClick={submitAndNext}>
            提交本份
          </Button>
        </div>
      </div>

      {!submissions.length ? (
        <div className="zh-empty-wrap">
          <EmptyState
            icon="keyboard"
            title="没有待批阅的作答"
            desc="请先在「扫描进卷」为试卷分配并确认学生作答"
            height="100%"
          />
        </div>
      ) : (
        <div className="zh-gbody">
          {/* 左：卷面（真实题目渲染为可读卷） */}
          <section className="zh-sheet">
            <div className="zh-sheet-head">
              <div>
                <div className="zh-sheet-student">{detail?.student_name || '考生'}的答卷</div>
                <div className="zh-sheet-sub">双击题区可放大 · 数字键/Enter 给分</div>
              </div>
              <div className="zh-sheet-tools">
                <button type="button" className="zh-tool" title="旋转">
                  <Icon name="rotate" size={18} />
                </button>
                <button type="button" className="zh-tool" title="放大">
                  <Icon name="zoom-in" size={18} />
                </button>
              </div>
            </div>
            <div className="zh-sheet-body">
              <div className="zh-sheet-page">
                {(detail?.questions ?? []).map((q) => (
                  <div
                    key={q.question_id}
                    className={`zh-q-block${scores[q.question_id] != null ? ' done' : ''}`}
                  >
                    <span className="zh-qb-no">{q.question_no}</span>
                    <div className="zh-qb-main">
                      <div className="zh-qb-content">
                        {q.content || '（无题干，请结合扫描卷面给分）'}
                      </div>
                      <div className="zh-qb-scoreline">
                        <span className="zh-qb-full">满分 {q.score} 分</span>
                        {scores[q.question_id] != null && (
                          <span className="zh-chip-done">已给分 {scores[q.question_id]}</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
                {!detail?.questions?.length && <div className="zh-no-q">该试卷尚未建题</div>}
              </div>
            </div>
          </section>

          {/* 右：评分面板（键盘流） */}
          <aside className="zh-score-panel">
            <div className="zh-sp-head">
              <span>逐题给分</span>
              <span className="zh-sp-progress">
                {answeredCount}/{detail?.questions.length ?? 0} · 小计 {totalScore} 分
              </span>
            </div>
            <div className="zh-sp-body">
              {(detail?.questions ?? []).map((q) => (
                <div key={q.question_id} className="zh-sp-row">
                  <span className="zh-sp-no">{q.question_no}</span>
                  <div className="zh-sp-info">
                    <div className="zh-sp-content">{q.content || '（无题干）'}</div>
                    <div className="zh-sp-meta">
                      <span>满分 {q.score}</span>
                      {q.ai_confidence != null && (
                        <span className="zh-ai-badge">
                          <Icon name="sparkles" size={12} />AI {Math.round((q.ai_confidence || 0) * 100)}%
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="zh-sp-input">
                    <InputNumber
                      value={scores[q.question_id] ?? undefined}
                      min={0}
                      max={q.score}
                      size="small"
                      onChange={(v) => {
                        setScores((prev) => ({ ...prev, [q.question_id]: v }))
                        void saveScore(q.question_id, Number(v ?? 0))
                      }}
                      style={{ flex: 1 }}
                    />
                    <button
                      type="button"
                      className="zh-full-btn"
                      onClick={() => {
                        setScores((prev) => ({ ...prev, [q.question_id]: q.score }))
                        void saveScore(q.question_id, q.score)
                      }}
                    >
                      满分
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <div className="zh-sp-keys">
              <div className="zh-key">
                <span>Enter</span>
                <em>满分配下一未答题</em>
              </div>
              <div className="zh-key">
                <span>数字</span>
                <em>直接键入得分</em>
              </div>
              <div className="zh-key">
                <span>[ / ]</span>
                <em>上一份 / 下一份</em>
              </div>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
