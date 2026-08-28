import { useEffect, useMemo, useState } from 'react'
import { App, Button, Form, Input, InputNumber, Modal, Select, Table } from 'antd'
import type { TableProps } from 'antd'
import { useNavigate } from 'react-router-dom'
import { examApi, scanApi } from '@/api'
import PageHeader from '@/components/PageHeader'
import FilterCard from '@/components/FilterCard'
import TableCard from '@/components/TableCard'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import Icon from '@/components/Icon'
import { SCAN_BATCH_STATUS_DICT } from '@/types/dict'
import type { ScanBatch } from '@/types'

interface PaperOption {
  id: number
  title: string
  examName: string
}

export default function ScanManage() {
  const { message, modal } = App.useApp()
  const navigate = useNavigate()

  const [loading, setLoading] = useState(false)
  const [batches, setBatches] = useState<ScanBatch[]>([])
  const [papers, setPapers] = useState<PaperOption[]>([])
  const [keyword, setKeyword] = useState('')
  const [appliedKeyword, setAppliedKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)

  // 新建批次
  const [createDlg, setCreateDlg] = useState(false)
  const [creating, setCreating] = useState(false)
  const [paperId, setPaperId] = useState<number>()
  const [fileName, setFileName] = useState('')
  const [pageCount, setPageCount] = useState(0)

  const paperTitle = (pid: number) => {
    const p = papers.find((x) => x.id === pid)
    return p ? `${p.examName} / ${p.title}` : `试卷 #${pid}`
  }

  const filteredBatches = useMemo(() => {
    const query = appliedKeyword.trim().toLowerCase()
    return batches.filter((item) => {
      if (!query) return true
      const fileName = (item.file_name || `扫描批次 #${item.id}`).toLowerCase()
      return fileName.includes(query) || paperTitle(item.paper_id).toLowerCase().includes(query)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batches, appliedKeyword, papers])

  const pagedBatches = useMemo(
    () => filteredBatches.slice((page - 1) * pageSize, page * pageSize),
    [filteredBatches, page, pageSize],
  )

  const handleSearch = () => {
    setAppliedKeyword(keyword)
    setPage(1)
  }

  const resetFilters = () => {
    setKeyword('')
    setAppliedKeyword('')
    setPage(1)
  }

  const loadBatches = async () => {
    setLoading(true)
    try {
      setBatches(await scanApi.batches())
    } catch (e) {
      message.error(e instanceof Error ? e.message : '批次加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadPapers = async () => {
    try {
      const exams = await examApi.list()
      const list: PaperOption[] = []
      for (const exam of exams) {
        const detail = await examApi.detail(exam.id)
        for (const p of detail.papers || []) {
          if (p.status === 'finalized') {
            list.push({ id: p.id, title: p.title, examName: exam.name })
          }
        }
      }
      setPapers(list)
    } catch (e) {
      message.error(e instanceof Error ? e.message : '试卷加载失败')
    }
  }

  useEffect(() => {
    void loadBatches()
    void loadPapers()
  }, [])

  // ---------- 新建批次 ----------
  const openCreate = () => {
    setPaperId(papers[0]?.id)
    setFileName('')
    setPageCount(0)
    setCreateDlg(true)
  }

  const saveBatch = async () => {
    if (!paperId) {
      message.warning('请选择试卷')
      return
    }
    setCreating(true)
    try {
      await scanApi.createBatch({
        paper_id: paperId,
        file_name: fileName.trim() || undefined,
        page_count: pageCount,
      })
      message.success('扫描批次已上传')
      setCreateDlg(false)
      await loadBatches()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '上传失败')
    } finally {
      setCreating(false)
    }
  }

  // ---------- 流程动作 ----------
  const doSplit = async (b: ScanBatch) => {
    try {
      await scanApi.split(b.id)
      message.success('已切分')
      await loadBatches()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '切分失败')
    }
  }

  const doAssign = async (b: ScanBatch) => {
    try {
      const r = await scanApi.assign(b.id)
      message.success(`已分配 ${r.created}/${r.total} 名学生的作答`)
      await loadBatches()
    } catch (e) {
      message.error(e instanceof Error ? e.message : '分配失败')
    }
  }

  const doConfirm = (b: ScanBatch) => {
    modal.confirm({
      title: '确认批次',
      content: '确认后将锁定该批次并进入打分流程，确定吗？',
      okText: '确认',
      cancelText: '取消',
      onOk: async () => {
        try {
          await scanApi.confirm(b.id)
          message.success('批次已确认')
          await loadBatches()
        } catch (e) {
          message.error(e instanceof Error ? e.message : '确认失败')
        }
      },
    })
  }

  const doGrading = (b: ScanBatch) => navigate(`/grading/${b.paper_id}`)

  const doReload = () => {
    message.info('真机可在此重新切分/矫正图像')
  }

  const columns: TableProps<ScanBatch>['columns'] = [
    {
      title: '批次',
      key: 'batch',
      render: (_, record) => (
        <div className="zh-batch-cell">
          <span className="zh-batch-icon">
            <Icon name="qrcode" size={16} />
          </span>
          <div>
            <div className="zh-batch-file">{record.file_name || `扫描批次 #${record.id}`}</div>
            <div className="zh-batch-paper">{paperTitle(record.paper_id)}</div>
          </div>
        </div>
      ),
    },
    {
      title: '页数',
      dataIndex: 'page_count',
      width: 80,
      align: 'center',
      render: (value?: number) => <span className="zh-num">{value ?? 0}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (value?: string) => <DictTag dict={SCAN_BATCH_STATUS_DICT} value={value} />,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 150,
      render: (value?: string) => <span className="zh-text-2">{(value || '').slice(0, 10)}</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 280,
      align: 'right',
      render: (_, record) => {
        if (record.status === 'uploaded') {
          return (
            <>
              <Button size="small" onClick={() => doReload()}>
                页码矫正
              </Button>
              <Button size="small" type="primary" onClick={() => doSplit(record)}>
                切分
              </Button>
            </>
          )
        }
        if (record.status === 'split') {
          return (
            <Button size="small" type="primary" onClick={() => doAssign(record)}>
              分配作答
            </Button>
          )
        }
        if (record.status === 'assigned') {
          return (
            <>
              <Button size="small" onClick={() => doGrading(record)}>
                去打分
              </Button>
              <Button size="small" type="primary" onClick={() => doConfirm(record)}>
                确认完成
              </Button>
            </>
          )
        }
        return (
          <Button size="small" onClick={() => doGrading(record)}>
            去打分
          </Button>
        )
      },
    },
  ]

  return (
    <div className="zh-page">
      <PageHeader
        title="扫描进卷"
        extra={
          <Button type="primary" icon={<Icon name="upload" size={16} />} onClick={openCreate}>
            新建批次
          </Button>
        }
      />
      <p className="zh-page-desc">上传扫描件 → 切分 → 按名册分配学生作答 → 确认进入打分</p>

      <FilterCard>
        <div className="zh-filter-row">
          <label className="zh-filter-field">
            <span>批次</span>
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              allowClear
              placeholder="文件名或试卷名称"
              style={{ width: 260 }}
            />
          </label>
          <Button type="primary" onClick={handleSearch}>
            查询
          </Button>
          <Button onClick={resetFilters}>重置</Button>
          <span className="zh-filter-count">当前 {filteredBatches.length} 条</span>
        </div>
      </FilterCard>

      <TableCard>
        <Table<ScanBatch>
          rowKey="id"
          columns={columns}
          dataSource={pagedBatches}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total: filteredBatches.length,
            onChange: (p, s) => {
              setPage(p)
              setPageSize(s)
            },
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
          locale={{
            emptyText: (
              <EmptyState
                icon="scan"
                title="暂无扫描批次"
                desc="请先定稿试卷，再上传扫描件建立批次"
                height={220}
                actionText="新建批次"
                onAction={openCreate}
              />
            ),
          }}
        />
      </TableCard>

      {/* 新建批次 */}
      <Modal
        title="上传扫描批次"
        open={createDlg}
        onCancel={() => setCreateDlg(false)}
        onOk={saveBatch}
        okText="上传"
        cancelText="取消"
        confirmLoading={creating}
        okButtonProps={{ disabled: !paperId }}
        width={480}
      >
        <Form layout="vertical">
          <Form.Item label="所属试卷" required>
            <Select
              value={paperId}
              onChange={setPaperId}
              placeholder="选择已定稿试卷"
              showSearch
              filterOption={(input, option) =>
                (option?.label as string).toLowerCase().includes(input.toLowerCase())
              }
              options={papers.map((p) => ({ label: `${p.examName} / ${p.title}`, value: p.id }))}
            />
          </Form.Item>
          <Form.Item label="批次名称">
            <Input
              value={fileName}
              onChange={(e) => setFileName(e.target.value)}
              placeholder="可为空，默认自动命名"
              maxLength={255}
            />
          </Form.Item>
          <Form.Item label="页数">
            <InputNumber
              value={pageCount}
              onChange={(v) => setPageCount(v ?? 0)}
              min={0}
              max={1000}
              style={{ width: '100%' }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
