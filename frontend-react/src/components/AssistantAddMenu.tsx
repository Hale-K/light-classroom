import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import Icon from './Icon'

type Props = { disabled: boolean; planMode: boolean; onPlanMode: () => void; onFiles: () => void; onFolder: () => void; onPage: () => void }

export default function AssistantAddMenu({ disabled, planMode, onPlanMode, onFiles, onFolder, onPage }: Props) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [open])
  useEffect(() => { if (disabled) setOpen(false) }, [disabled])
  const choose = (action: () => void) => { setOpen(false); trigger.current?.focus(); action() }
  const keys = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); return }
    if (event.key === 'Tab') { setOpen(false); return }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const items = Array.from(root.current?.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]:not(:disabled)') ?? [])
    const index = items.indexOf(document.activeElement as HTMLButtonElement)
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + items.length) % items.length
    items[next]?.focus()
  }
  return <div className="assist-add" ref={root} onKeyDown={keys}>
    <button ref={trigger} type="button" className="assist-plus" title="添加" aria-label="添加附件和上下文"
      aria-haspopup="menu" aria-expanded={open} disabled={disabled} onClick={() => setOpen(value => !value)}>
      <Icon name="plus" size={16} />
    </button>
    {open && <div className="assist-add-menu" role="menu" aria-label="添加">
      <span className="assist-add-label">添加资料</span>
      <button role="menuitem" type="button" onClick={() => choose(onFiles)}><Icon name="file-text" size={18} /><span>上传文件</span></button>
      <button role="menuitem" type="button" onClick={() => choose(onFolder)}><Icon name="book" size={18} /><span>选择文件夹</span></button>
      <button role="menuitem" type="button" onClick={() => choose(onPage)}><Icon name="dashboard" size={18} /><span>附加当前页面</span></button>
      <span className="assist-add-label assist-add-divider">工作方式</span>
      <button role="menuitemcheckbox" aria-checked={planMode} title="只分析，不修改" type="button" onClick={() => choose(onPlanMode)}><Icon name="clipboard" size={18} /><span>计划模式</span><span className={`assist-menu-switch${planMode ? ' is-on' : ''}`} aria-hidden="true" /></button>
      <button role="menuitem" type="button" disabled><Icon name="scan" size={18} /><span>持续目标</span><small className="assist-menu-status">待接入</small></button>
      <button role="menuitem" type="button" disabled><Icon name="chart" size={18} /><span>绘图</span><small className="assist-menu-status">待接入</small></button>
      <div className="assist-add-divider"><button role="menuitem" type="button" disabled><Icon name="sitemap" size={18} /><span>外部插件</span><small className="assist-menu-status">未连接</small></button></div>
    </div>}
  </div>
}
