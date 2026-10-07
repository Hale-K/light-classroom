/** files 领域 API（由 api/index.ts 拆分）。 */
import { http, unwrap } from './http'

export type FileTransferJobType = {
  value: string
  label: string
  direction: 'import' | 'export'
}

export type FileTransferJob = {
  id: string
  job_type: string
  job_type_label: string
  direction: 'import' | 'export'
  status: 'queued' | 'running' | 'success' | 'failed' | string
  progress: number
  processed: number
  total: number
  operator_id?: number | null
  operator_name?: string
  scope?: string
  file_name?: string | null
  object_key?: string | null
  file_size: number
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  duration_ms?: number | null
  downloadable?: boolean
}

/** 文件中心：异步导入 / 导出 / 下载 */
export const fileCenterApi = {
  jobTypes: () => unwrap<FileTransferJobType[]>(http.get('/file-center/job-types')),
  listJobs: (params?: { direction?: string; job_type?: string; status?: string; limit?: number }) =>
    unwrap<FileTransferJob[]>(http.get('/file-center/jobs', { params })),
  getJob: (jobId: string) => unwrap<FileTransferJob>(http.get(`/file-center/jobs/${jobId}`)),
  download: (jobId: string) =>
    unwrap<{ url: string; file_name?: string; file_size?: number }>(
      http.get(`/file-center/jobs/${jobId}/download`),
    ),
  exportTimetable: (data: {
    academic_year: string
    term: string
    class_ids?: number[] | null
    periods_per_day?: number
    evening_start_period?: number | null
    sheets?: string[]
    student_zip?: boolean
  }) => unwrap<FileTransferJob>(http.post('/file-center/exports/timetable', data)),
  exportStudents: (data: {
    grade_id?: number | null
    class_id?: number | null
    unassigned_only?: boolean
  }) => unwrap<FileTransferJob>(http.post('/file-center/exports/students', data)),
  createImport: (data: { job_type: string; file: File; scope?: string }) => {
    const body = new FormData()
    body.append('job_type', data.job_type)
    if (data.scope) body.append('scope', data.scope)
    body.append('file', data.file)
    return unwrap<FileTransferJob>(http.post('/file-center/imports', body))
  },
}

/** 教师档案 */
