import { Card, Empty, Typography } from 'antd'
import PageHeader from '@/components/PageHeader'

export default function KnowledgeView() {
  return (
    <div className="zh-page">
      <PageHeader title="知识库" />
      <Card>
        <Empty description="知识库管理即将开放">
          <Typography.Text type="secondary">
            下一步将支持文档上传、解析进度、向量化状态和检索测试。
          </Typography.Text>
        </Empty>
      </Card>
    </div>
  )
}
