import { App, Button, Card, Form, Input, Modal, Space, Switch, Table } from 'antd'
import { useEffect, useState } from 'react'
import PageHeader from '@/components/PageHeader'
import { knowledgeApi, type KnowledgeBase } from '@/api'

export default function KnowledgeView() {
  const { message } = App.useApp()
  const [rows, setRows] = useState<KnowledgeBase[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const load = async () => { try { setRows(await knowledgeApi.list()) } catch { message.error('知识库加载失败') } }
  useEffect(() => { void load() }, [])
  const create = async () => { try { await knowledgeApi.create({ ...form.getFieldsValue(), embedding_model: 'bge-base-zh-v1.5' }); message.success('已创建'); setOpen(false); form.resetFields(); void load() } catch { message.error('创建失败') } }
  return (
    <div className="zh-page">
      <PageHeader title="知识库" extra={<Button type="primary" onClick={() => setOpen(true)}>新建知识库</Button>} />
      <Card>
        <Table rowKey="id" dataSource={rows} columns={[
          { title: '名称', dataIndex: 'name' }, { title: '描述', dataIndex: 'description' },
          { title: '向量模型', dataIndex: 'embedding_model' },
          { title: '状态', render: (_: unknown, row: KnowledgeBase) => <Switch checked={row.enabled} onChange={async (v) => { await knowledgeApi.setStatus(row.id, v); void load() }} /> },
          { title: '操作', render: (_: unknown, row: KnowledgeBase) => <Space><Button danger onClick={async () => { await knowledgeApi.remove(row.id); void load() }}>删除</Button></Space> },
        ]} />
      </Card>
      <Modal title="新建知识库" open={open} onCancel={() => setOpen(false)} onOk={() => void create()}>
        <Form form={form} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={4} /></Form.Item></Form>
      </Modal>
    </div>
  )
}
