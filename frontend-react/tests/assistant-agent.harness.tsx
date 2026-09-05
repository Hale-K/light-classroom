import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import AssistantDock from '../src/components/AssistantDock'

createRoot(document.getElementById('root')!).render(<BrowserRouter><AssistantDock /></BrowserRouter>)
