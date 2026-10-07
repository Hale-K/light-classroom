/** onboarding 领域 API（由 api/index.ts 拆分）。 */
import { http, unwrap, setAuthResolver } from './http'

export type OnboardingStep = {
  key: string
  title: string
  done: boolean
  detail: string
  path: string
}

export type OnboardingStatus = {
  steps: OnboardingStep[]
  done_count: number
  total: number
  history_year?: string | null
  dismissed: boolean
  audience?: 'management' | 'head_teacher' | 'subject_teacher'
}

export const onboardingApi = {
  status: (signal?: AbortSignal) =>
    unwrap<OnboardingStatus>(http.get('/onboarding/status', { timeout: 8000, signal })),
  dismiss: () => unwrap<{ dismissed: boolean }>(http.post('/onboarding/dismiss', {}, { timeout: 8000 })),
  reopen: () => unwrap<{ dismissed: boolean }>(http.post('/onboarding/reopen', {}, { timeout: 8000 })),
}

export { setAuthResolver }
