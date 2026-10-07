/** auth 领域 API（由 api/index.ts 拆分）。 */
import type {
  MenuResult,
  UserInfo,
} from '@/types'
import { http, unwrap } from './http'

export interface LoginResult {
  access_token: string
  token_type: string
  user: UserInfo
  /** 账号所属学校，登录后由后端决定，前端无需预选 */
  school?: {
    code: string | null
    name: string | null
    province: string | null
    gaokao_mode: '3+1+2' | '3+3' | 'traditional' | null
  }
}

export interface SchoolSettings {
  id: number
  code: string
  name: string
  province: string
  gaokao_mode: '3+1+2' | '3+3' | 'traditional'
  timetable_mode: 'administrative' | 'walk_class'
}

export interface AcademicYearEntry {
  entry_year: number
  cohort_label: string
  grade_years: { 高一: string; 高二: string; 高三: string }
  status: 'active' | 'inactive'
}
export interface AcademicYearsSettings {
  years: AcademicYearEntry[]
  current_entry_year: number | null
  current_academic_year: string | null
  current_term: '1' | '2'
}

const settingsCacheKey = (name: string) => {
  const schoolCode = localStorage.getItem('zh_school_code') || 'default'
  return `light-classroom:settings:${schoolCode}:${name}`
}

function readSettingsCache<T>(name: string): T | null {
  try {
    const raw = localStorage.getItem(settingsCacheKey(name))
    return raw ? JSON.parse(raw) as T : null
  } catch {
    return null
  }
}

function writeSettingsCache<T>(name: string, value: T): T {
  try { localStorage.setItem(settingsCacheKey(name), JSON.stringify(value)) } catch { /* storage may be unavailable */ }
  return value
}

function clearSettingsCache(name: string) {
  localStorage.removeItem(settingsCacheKey(name))
}
export interface AcademicYearRolloverPreview {
  source_entry_year: number
  source_cohort_label: string
  target_entry_year: number
  target_cohort_label: string
  source_academic_year: string
  target_academic_year: string
  class_count: number
  student_count: number
  promote_high_one_classes: number
  promote_high_two_classes: number
  graduate_high_three_classes: number
  already_done: boolean
  warnings: string[]
}

export const authApi = {
  login: (phone: string, password: string) =>
    unwrap<LoginResult>(http.post('/auth/login', { phone, password })),
  register: (data: { name: string; phone: string; password: string; role?: string }) =>
    unwrap<UserInfo>(http.post('/auth/register', data)),
  me: () => unwrap<UserInfo>(http.get('/auth/me')),
  menus: () => unwrap<MenuResult>(http.get('/auth/menus')),
  school: async (refresh = false) => {
    if (!refresh) {
      const cached = readSettingsCache<SchoolSettings>('school')
      if (cached) return cached
    }
    return writeSettingsCache('school', await unwrap<SchoolSettings>(http.get('/auth/school')))
  },
  updateSchool: async (data: {
    province?: string
    gaokao_mode?: '3+1+2' | '3+3' | 'traditional'
    timetable_mode?: 'administrative' | 'walk_class'
  }) => {
    const updated = await unwrap<SchoolSettings>(http.patch('/auth/school', data))
    return writeSettingsCache('school', updated)
  },
  academicYears: async (refresh = false) => {
    if (!refresh) {
      const cached = readSettingsCache<AcademicYearsSettings>('academic-years')
      if (cached) return cached
    }
    return writeSettingsCache('academic-years', await unwrap<AcademicYearsSettings>(http.get('/auth/academic-years')))
  },
  previewAcademicYearRollover: (source_entry_year: number) =>
    unwrap<AcademicYearRolloverPreview>(http.post('/auth/academic-year-rollover/preview', { source_entry_year })),
  commitAcademicYearRollover: async (source_entry_year: number) => {
    const result = await unwrap<{ current_entry_year: number; current_academic_year: string; current_term: '1' | '2'; promoted_student_count: number; created_class_count: number }>(
      http.post('/auth/academic-year-rollover/commit', { source_entry_year }),
    )
    clearSettingsCache('academic-years')
    return result
  },
  saveAcademicYears: async (years: Array<{ entry_year: number; status: 'active' | 'inactive' }>, current_entry_year?: number | null, current_academic_year?: string | null, current_term?: '1' | '2') => {
    const result = await unwrap<AcademicYearsSettings>(http.put('/auth/academic-years', { years, current_entry_year, current_academic_year, current_term }))
    return writeSettingsCache('academic-years', result)
  },
}

/** 平台超管 API（创建学校后台） */
export interface StudentLoginResult {
  access_token: string
  token_type: string
  student: { id: number; name: string; student_no?: string | null; grade_id?: number | null; class_id?: number | null }
  school: { code: string; name: string; province: string }
}

export interface StudentSchoolOption {
  code: string
  name: string
  province: string
}

export interface StudentChoiceOptions {
  scheme: {
    id: number
    name: string
    mode: '3+1+2' | '3+3' | 'traditional'
    required_subject_ids: number[]
    primary_subject_ids: number[]
    secondary_subject_ids: number[]
  } | null
  subjects: Array<{ id: number; name: string }>
  choice: {
    scheme_id: number
    primary_subject_id?: number | null
    secondary_subject_ids: number[]
    status: 'draft' | 'confirmed' | 'rejected' | 'locked'
  } | null
}

export const studentAuthApi = {
  schools: () => unwrap<StudentSchoolOption[]>(http.get('/student-auth/schools')),
  login: (data: { login_name: string; password: string }) =>
    unwrap<StudentLoginResult>(http.post('/student-auth/login', data)),
  me: () => unwrap<StudentLoginResult['student']>(http.get('/student-auth/me')),
  context: () => unwrap<{ academic_year: string; term: string; student: StudentLoginResult['student'] }>(http.get('/student-auth/context')),
  options: (params: { academic_year: string; term: string }) =>
    unwrap<StudentChoiceOptions>(http.get('/student-auth/choice/options', { params })),
  choice: (params: { academic_year: string; term: string }) =>
    unwrap<unknown>(http.get('/student-auth/choice', { params })),
  saveChoice: (data: {
    scheme_id: number
    academic_year: string
    effective_term: string
    primary_subject_id?: number
    secondary_subject_ids: number[]
    status: 'draft' | 'confirmed'
  }) => unwrap<StudentChoiceOptions['choice']>(http.put('/student-auth/choice', data)),
}

