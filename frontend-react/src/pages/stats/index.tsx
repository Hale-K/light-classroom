import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { App, Spin } from 'antd'
import * as echarts from 'echarts'
import { statsApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import EmptyState from '@/components/EmptyState'
import type { PaperSummary } from '@/types'
import './index.css'

type Row = Record<string, unknown>

/** 成绩统计 · 试卷打分后统计页 */
export default function StatsView() {
  const { paperId: paperIdParam } = useParams<{ paperId: string }>()
  const paperId = Number(paperIdParam)
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<PaperSummary | null>(null)
  const [byClass, setByClass] = useState<Row[]>([])
  const [byQuestion, setByQuestion] = useState<Row[]>([])

  const distRef = useRef<HTMLDivElement>(null)
  const classRef = useRef<HTMLDivElement>(null)
  const qRef = useRef<HTMLDivElement>(null)

  const hasData = !!(summary && summary.count)

  // ECharts 配色：墨色主系列 + pastel 家族 ink 辅色，去掉默认渐变
  const colors = {
    primary: '#111111',
    blue: '#1f6c9f',
    amber: '#956400',
    line: '#eaeaea',
    lineLight: '#f0f0ef',
    text: '#787774',
  }

  // 加载数据
  useEffect(() => {
    let cancelled = false
    void (async () => {
      setLoading(true)
      try {
        const [s, cl, q] = await Promise.all([
          statsApi.paperSummary(paperId),
          statsApi.paperByClass(paperId),
          statsApi.paperByQuestion(paperId),
        ])
        if (cancelled) return
        setSummary(s)
        setByClass(cl)
        setByQuestion(q)
      } catch {
        if (!cancelled) message.error('加载成绩统计失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [paperId, message])

  const ensureChart = (el: HTMLElement) => echarts.getInstanceByDom(el) || echarts.init(el)

  const renderDist = (el: HTMLElement) => {
    const dist = summary?.distribution || []
    ensureChart(el).setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 30, right: 12, top: 16, bottom: 26 },
      xAxis: {
        type: 'category',
        data: dist.map((d) => `${d.label}分`),
        axisLine: { lineStyle: { color: colors.line } },
        axisLabel: { color: colors.text },
      },
      yAxis: { type: 'value', minInterval: 1, splitLine: { lineStyle: { color: colors.lineLight } } },
      series: [
        {
          type: 'bar',
          data: dist.map((d) => d.count),
          barWidth: 34,
          itemStyle: { color: colors.primary, borderRadius: [6, 6, 0, 0] },
        },
      ],
    })
  }

  const renderClass = (el: HTMLElement) => {
    ensureChart(el).setOption({
      tooltip: { trigger: 'axis' },
      legend: { bottom: 0, icon: 'circle', itemWidth: 10, textStyle: { color: colors.text } },
      grid: { left: 36, right: 12, top: 20, bottom: 60 },
      xAxis: {
        type: 'category',
        data: byClass.map((c) => (c.class_name as string) || '未分班'),
        axisLabel: { color: colors.text },
      },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: colors.lineLight } } },
      series: [
        {
          name: '均分',
          type: 'bar',
          data: byClass.map((c) => (c.mean as number) || 0),
          barWidth: 28,
          itemStyle: { color: colors.primary, borderRadius: [6, 6, 0, 0] },
        },
        {
          name: '人数',
          type: 'line',
          data: byClass.map((c) => (c.count as number) || 0),
          smooth: true,
          symbolSize: 6,
          itemStyle: { color: colors.blue },
        },
      ],
    })
  }

  const renderQuestion = (el: HTMLElement) => {
    ensureChart(el).setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 36, right: 40, top: 16, bottom: 26 },
      xAxis: {
        type: 'category',
        data: byQuestion.map((q) => `题${q.question_no}`),
        axisLabel: { color: colors.text },
      },
      yAxis: [
        { type: 'value', name: '均分', splitLine: { lineStyle: { color: colors.lineLight } }, axisLabel: { color: colors.text } },
        {
          type: 'value',
          name: '得分率',
          max: 1,
          min: 0,
          axisLabel: { formatter: (v: number) => `${Math.round(v * 100)}%`, color: colors.text },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '均分',
          type: 'bar',
          data: byQuestion.map((q) => (q.mean as number) || 0),
          barWidth: 22,
          itemStyle: { color: colors.primary, borderRadius: [6, 6, 0, 0] },
        },
        {
          name: '得分率',
          type: 'line',
          yAxisIndex: 1,
          data: byQuestion.map((q) => (q.score_rate as number) || 0),
          smooth: true,
          symbolSize: 6,
          itemStyle: { color: colors.amber },
        },
      ],
    })
  }

  const renderAll = () => {
    const distEl = distRef.current
    const classEl = classRef.current
    const qEl = qRef.current
    if (distEl) renderDist(distEl)
    if (classEl) renderClass(classEl)
    if (qEl) renderQuestion(qEl)
  }

  // 数据就绪且图表容器挂载后初始化图表 + 渲染
  useEffect(() => {
    if (!hasData) return
    const charts = [distRef.current, classRef.current, qRef.current]
      .filter((el): el is HTMLDivElement => !!el)
      .map((el) => ensureChart(el))
    const onResize = () => charts.forEach((c) => c.resize())
    window.addEventListener('resize', onResize)
    renderAll()
    return () => {
      window.removeEventListener('resize', onResize)
      charts.forEach((c) => c.dispose())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [summary, byClass, byQuestion])

  return (
    <div className="st-page">
      <PageHeader title={`成绩统计 · 试卷 #${paperId}`} />
      <Spin spinning={loading}>
        {hasData ? (
          <>
            {/* 汇总卡片 */}
            <div className="st-sum-cards">
              <div className="st-sum-card">
                <div className="st-sum-num">{summary.count}</div>
                <div className="st-sum-label">参测人数</div>
              </div>
              <div className="st-sum-card">
                <div className="st-sum-num st-blue">{summary.mean}</div>
                <div className="st-sum-label">平均分</div>
              </div>
              <div className="st-sum-card">
                <div className="st-sum-num st-green">{summary.max}</div>
                <div className="st-sum-label">最高分</div>
              </div>
              <div className="st-sum-card">
                <div className="st-sum-num st-amber">{summary.min}</div>
                <div className="st-sum-label">最低分</div>
              </div>
            </div>

            {/* 图表 */}
            <div className="st-charts">
              <section className="st-card">
                <h3>分数段分布</h3>
                <div ref={distRef} className="st-chart" />
              </section>
              <section className="st-card">
                <h3>班级对比 · 均分与人数</h3>
                <div ref={classRef} className="st-chart" />
              </section>
              <section className="st-card st-wide">
                <h3>逐题得分 · 均分与得分率（蓝线为得分率）</h3>
                <div ref={qRef} className="st-chart" />
              </section>
            </div>
          </>
        ) : (
          !loading && (
            <div className="st-empty-wrap">
              <EmptyState
                icon="chart"
                title="暂无成绩数据"
                desc={summary ? '该卷尚无人完成批阅，或尚未生成成绩' : '无法加载该试卷统计'}
                height={360}
              />
            </div>
          )
        )}
      </Spin>
    </div>
  )
}
