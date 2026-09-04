import { useCallback, useEffect, useMemo, useState } from 'react'
import { App, Button, Progress, Select, Space, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import PageHeader from '@/components/PageHeader'
import TableCard from '@/components/TableCard'
import { fileCenterApi, type FileTransferJob, type FileTransferJobType } from '@/api'
import './index.css'

const STATUS_LABEL: Record<string, { color: string; text: string }> = {
  queued: { color: 'default', text: '排队中' },
  running: { color: 'processing', text: '进行中' },
  success: { color: 'success', text: '成功' },
  failed: { color: 'error', text: '失败' },
}

function formatBytes(size: number) {
  if (!size) return '—'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function formatDuration(ms: number | null | undefined) {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(1)} s`
}

export default function FileCenterView() {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [jobs, setJobs] = useState<FileTransferJob[]>([])
  const [types, setTypes] = useState<FileTransferJobType[]>([])
  const [direction, setDirection] = useState<'import' | 'export' | undefined>()
  const [jobType, setJobType] = useState<string | undefined>()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [typeRows, rows] = await Promise.all([
        fileCenterApi.jobTypes(),
        fileCenterApi.listJobs({ direction, job_type: jobType, limit: 100 }),
      ])
      setTypes(typeRows)
      setJobs(rows)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [direction, jobType, message])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const hasRunning = jobs.some((item) => item.status === 'queued' || item.status === 'running')
    if (!hasRunning) return
    const timer = window.setInterval(() => {
      void load()
    }, 2000)
    return () => window.clearInterval(timer)
  }, [jobs, load])

  const typeOptions = useMemo(
    () =>
      types
        .filter((item) => !direction || item.direction === direction)
        .map((item) => ({ value: item.value, label: item.label })),
    [types, direction],
  )

  const onDownload = async (job: FileTransferJob) => {
    try {
      const data = await fileCenterApi.download(job.id)
      window.open(data.url, '_blank')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '下载失败')
    }
  }

  const columns: ColumnsType<FileTransferJob> = [
    {
      title: '类型',
      dataIndex: 'job_type_label',
      width: 140,
      render: (value, row) => (
        <Space size={6}>
          <Tag color={row.direction === 'export' ? 'blue' : 'purple'}>
            {row.direction === 'export' ? '导出' : '导入'}
          </Tag>
          <span>{value}</span>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value: string) => {
        const meta = STATUS_LABEL[value] || { color: 'default', text: value }
        return <Tag color={meta.color}>{meta.text}</Tag>
      },
    },
    {
      title: '进度',
      dataIndex: 'progress',
      width: 160,
      render: (value: number, row) => (
        <div className="fc-progress">
          <Progress
            percent={value}
            size="small"
            status={row.status === 'failed' ? 'exception' : row.status === 'success' ? 'success' : 'active'}
          />
          <small>{row.processed}/{row.total || '—'}</small>
        </div>
      ),
    },
    { title: '操作人', dataIndex: 'operator_name', width: 100, render: (v) => v || '—' },
    { title: '范围', dataIndex: 'scope', ellipsis: true },
    {
      title: '文件',
      dataIndex: 'file_name',
      width: 180,
      ellipsis: true,
      render: (value, row) => (
        <div>
          <div>{value || '—'}</div>
          <small>{formatBytes(row.file_size)}</small>
        </div>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (value?: string) => (value ? value.replace('T', ' ').slice(0, 19) : '—'),
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 90,
      render: (value) => formatDuration(value),
    },
    {
      title: '失败原因',
      dataIndex: 'error_message',
      ellipsis: true,
      render: (value) => value || '—',
    },
    {
      title: '操作',
      key: 'actions',
      width: 100,
      fixed: 'right',
      render: (_, row) => (
        <Button
          type="link"
          size="small"
          disabled={!row.downloadable}
          onClick={() => void onDownload(row)}
        >
          下载
        </Button>
      ),
    },
  ]

  return (
    <div className="fc-page">
      <PageHeader
        title="文件中心"
        desc="查看导入、导出任务进度；完成后可下载文件。"
      />
      <TableCard
        title="任务列表"
        extra={(
          <Space wrap>
            <Select
              allowClear
              placeholder="导入/导出"
              style={{ width: 120 }}
              value={direction}
              onChange={(value) => {
                setDirection(value)
                setJobType(undefined)
              }}
              options={[
                { value: 'export', label: '导出' },
                { value: 'import', label: '导入' },
              ]}
            />
            <Select
              allowClear
              placeholder="类型"
              style={{ width: 180 }}
              value={jobType}
              onChange={setJobType}
              options={typeOptions}
            />
            <Button onClick={() => void load()}>刷新</Button>
          </Space>
        )}
      >
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={jobs}
          scroll={{ x: 1200 }}
          pagination={{ pageSize: 20, showSizeChanger: false }}
        />
      </TableCard>
    </div>
  )
}
