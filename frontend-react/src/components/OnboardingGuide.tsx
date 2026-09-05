import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { onboardingApi } from '@/api'
import Icon from '@/components/Icon'

/** 顶栏「新手引导 N/9」胶囊：展示真实进度，点击进入引导大页；跳过后全校隐藏。 */
export default function OnboardingGuide() {
  const navigate = useNavigate()
  const location = useLocation()
  const [doneCount, setDoneCount] = useState(0)
  const [total, setTotal] = useState(9)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    if (dismissed) return
    onboardingApi.status()
      .then((data) => {
        setDoneCount(data.done_count ?? 0)
        setTotal(data.total || 9)
        setDismissed(Boolean(data.dismissed))
      })
      .catch(() => undefined)
  }, [location.pathname, dismissed])

  if (dismissed) return null
  const allDone = total > 0 && doneCount >= total
  return (
    <button
      type="button"
      className={`guide-chip${allDone ? ' is-done' : ''}`}
      onClick={() => navigate('/onboarding')}
    >
      <Icon name="sparkles" size={14} />
      <span>新手引导 {doneCount}/{total}</span>
    </button>
  )
}
