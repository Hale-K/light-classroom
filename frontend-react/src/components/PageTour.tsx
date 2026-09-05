import { Button, Tour } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { tourForPathname, resolveTarget, type TourStep } from '@/tour/tours'

const TARGET_WAIT_MS = 1500

function targetElement(step: TourStep): HTMLElement | null {
  const element = resolveTarget(step.target)
  if (!(element instanceof HTMLElement)) return null
  const rect = element.getBoundingClientRect()
  return rect.width >= 2 && rect.height >= 2 ? element : null
}

async function waitForTarget(step: TourStep): Promise<HTMLElement | null> {
  const started = performance.now()
  let element = targetElement(step)
  while (!element && performance.now() - started < TARGET_WAIT_MS) {
    await new Promise<void>((resolve) => window.setTimeout(resolve, 30))
    element = targetElement(step)
  }
  return element
}

/** 顶栏「本页导览」：业务文案由页面配置，定位与越界处理交给 Ant Design Tour。 */
export default function PageTour() {
  const location = useLocation()
  const configured = useMemo(() => tourForPathname(location.pathname) ?? [], [location.pathname])
  const [live, setLive] = useState<TourStep[] | null>(null)
  const [current, setCurrent] = useState(0)
  const [switching, setSwitching] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)

  const finish = () => {
    setLive(null)
    setCurrent(0)
    setSwitching(false)
    window.requestAnimationFrame(() => triggerRef.current?.focus())
  }

  useEffect(() => {
    setLive(null)
    setCurrent(0)
  }, [location.pathname])

  useEffect(() => {
    if (!live) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') finish()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [live])

  const start = async () => {
    const available = configured.filter((step) => step.beforeEnter || targetElement(step) !== null)
    if (!available.length) return
    await available[0].beforeEnter?.()
    if (!await waitForTarget(available[0])) return
    setLive(available)
    setCurrent(0)
  }

  const changeStep = async (next: number) => {
    const step = live?.[next]
    if (!step || switching) return
    setSwitching(true)
    try {
      await step.beforeEnter?.()
      if (await waitForTarget(step)) setCurrent(next)
    } finally {
      setSwitching(false)
    }
  }

  const steps = (live ?? []).map((step, index) => ({
    title: `第 ${index + 1} 步 · ${step.title}`,
    description: step.content,
    target: () => targetElement(step)!,
    placement: 'bottom' as const,
    nextButtonProps: { children: index === (live?.length ?? 0) - 1 ? '完成' : '下一步', loading: switching, disabled: switching },
    prevButtonProps: { children: '上一步', disabled: switching },
    scrollIntoViewOptions: { block: 'center' as const, inline: 'nearest' as const, behavior: 'smooth' as const },
  }))

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="guide-chip"
        aria-haspopup="dialog"
        aria-expanded={Boolean(live)}
        onClick={() => void start()}
      >
        <span className="tour-q">?</span>
        <span>本页导览</span>
      </button>
      <Tour
        rootClassName="lc-page-tour"
        open={Boolean(live)}
        current={current}
        steps={steps}
        onChange={(next) => void changeStep(next)}
        onClose={finish}
        onFinish={finish}
        arrow={{ pointAtCenter: true }}
        gap={{ offset: 6, radius: 4 }}
        mask={{ color: 'rgba(5, 8, 18, 0.72)' }}
        zIndex={1300}
        actionsRender={(originNode) => (
          <>
            <Button type="text" size="small" onClick={finish}>跳过</Button>
            {originNode}
          </>
        )}
      />
    </>
  )
}
