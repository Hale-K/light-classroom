import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { App, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import ExamSchedulingView from '../src/pages/exam-scheduling'
import '../src/index.css'
import { installPlanningDemo } from './exam-planning-demo'

if (new URLSearchParams(window.location.search).get('visualDemo') === '1') installPlanningDemo()

createRoot(document.getElementById('root')!).render(<BrowserRouter><ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#098fce', borderRadius: 8, fontFamily: '"Microsoft YaHei", sans-serif' } }}><App><main style={{ maxWidth: 1440, margin: 'auto', padding: 24 }}><ExamSchedulingView /></main></App></ConfigProvider></BrowserRouter>)
