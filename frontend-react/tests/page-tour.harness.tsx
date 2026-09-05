import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, useLocation, useSearchParams } from 'react-router-dom'
import PageTour from '@/components/PageTour'
import '@/index.css'

const schedulingTabs = ['课时管理', '课位结构', '任教关系', '建立规则', '课表'] as const
type SchedulingTab = typeof schedulingTabs[number]

function SchedulingHarness() {
  const [active, setActive] = useState<SchedulingTab>('课位结构')
  const [, setSearchParams] = useSearchParams()
  const select = (tab: SchedulingTab) => {
    setActive(tab)
    setSearchParams({ tab }, { replace: true })
  }
  return (
    <main className="zh-page">
      <div className="sk-tabs">
        <div role="tablist">
          {schedulingTabs.map((tab) => (
            <button key={tab} role="tab" aria-selected={active === tab} type="button" onClick={() => select(tab)}>{tab}</button>
          ))}
        </div>
        {active === '课时管理' && <section className="sk-hours"><div className="sk-hours-intro">课时范围</div><div className="sk-hours-table">课时方案表格</div></section>}
        {active === '课位结构' && <section className="slot-structure-panel">课位结构配置</section>}
        {active === '任教关系' && <section className="sk-assign"><div className="sk-assign-filters">任教筛选</div><div className="ant-table-wrapper">任教列表</div></section>}
        {active === '建立规则' && <section className="st-rules"><div className="rule-group-page">规则工作台</div></section>}
        {active === '课表' && <section className="sk-schedule-workspace"><div className="sk-schedule-surface"><div className="sk-calendar-actions"><button>生成课表</button></div>课表结果</div></section>}
      </div>
    </main>
  )
}

function PageContent() {
  const location = useLocation()
  if (location.pathname.startsWith('/scheduling')) return <SchedulingHarness />
  return (
    <main className="zh-page">
      <div className="chapter"><h2>空间资源</h2></div>
      <div className="zh-stat-strip"><span>学生总数 <strong>12</strong></span><span>待分班 <strong>3</strong></span></div>
      <div className="facility-tabs"><div className="ant-tabs-nav"><div className="ant-tabs-nav-list" role="tablist">页面页签</div></div></div>
      <div className="facility-actions" style={{ display: 'flex', justifyContent: 'flex-end' }}><button type="button">新增校区</button></div>
      <aside className="facility-tree-panel">学校空间树</aside>
      <section className="facility-directory">资源详情</section>
    </main>
  )
}

function Harness() {
  return (
    <BrowserRouter>
      <header><PageTour /></header>
      <PageContent />
    </BrowserRouter>
  )
}

createRoot(document.getElementById('root')!).render(<Harness />)
