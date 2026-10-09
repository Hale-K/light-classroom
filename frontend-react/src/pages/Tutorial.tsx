import { useState } from 'react'
import { Button, Layout, Typography, Alert, Divider, Image } from 'antd'
import { ArrowLeftOutlined, BookOutlined, SettingOutlined, QuestionCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Sider, Content } = Layout
const { Title, Paragraph } = Typography

interface DocSection {
  key: string
  label: string
  icon?: React.ReactNode
}

const SECTIONS: DocSection[] = [
  { key: 'intro', label: '功能简介', icon: <BookOutlined /> },
  { key: 'prepare', label: '准备工作', icon: <SettingOutlined /> },
  { key: 'settings', label: '系统设置' },
  { key: 'faq', label: '常见问题', icon: <QuestionCircleOutlined /> },
]

export default function TutorialPage() {
  const navigate = useNavigate()
  const [active, setActive] = useState('intro')

  const scrollTo = (key: string) => {
    setActive(key)
    document.getElementById(`doc-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <div style={{ padding: '16px 24px' }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
          返回
        </Button>
      </div>
      <Layout style={{ background: '#fff', margin: '0 24px 24px', borderRadius: 8, minHeight: 'calc(100vh - 120px)' }}>
        <Sider width={240} style={{ background: '#fff', borderRight: '1px solid #f0f0f0', borderRadius: '8px 0 0 8px' }}>
          <div style={{ padding: '20px 16px', borderBottom: '1px solid #f0f0f0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, fontSize: 15 }}>
              <BookOutlined style={{ color: '#1677ff' }} />
              帮助文档
            </div>
          </div>
          <div style={{ padding: '12px 0' }}>
            {SECTIONS.map((s) => (
              <div
                key={s.key}
                onClick={() => scrollTo(s.key)}
                style={{
                  padding: '10px 24px',
                  cursor: 'pointer',
                  color: active === s.key ? '#1677ff' : '#595959',
                  background: active === s.key ? '#e6f4ff' : 'transparent',
                  fontWeight: active === s.key ? 500 : 400,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  fontSize: 14,
                }}
              >
                {s.icon}
                {s.label}
              </div>
            ))}
          </div>
        </Sider>
        <Content style={{ padding: '32px 40px', background: '#fff', borderRadius: '0 8px 8px 0', overflow: 'auto' }}>
          <div id="doc-intro">
            <Title level={3}>一、功能简介</Title>
            <Paragraph>
              轻课堂教务管理系统为学校提供一站式的教学管理解决方案，涵盖排课、成绩、学生档案、教师管理、考试组织等核心模块。
            </Paragraph>
          </div>
          <Divider />
          <div id="doc-prepare">
            <Title level={3}>二、使用前准备工作</Title>
            <Alert
              type="info"
              showIcon
              message="在开始使用系统前，请确认已完成学校基础数据的初始化配置。"
              style={{ marginBottom: 24 }}
            />
            <Title level={4}>2.1 创建组织架构</Title>
            <Paragraph>
              在「人员账号」中点击「新建组织」，可直接创建年级部和学科教研组。年级中心属于可选管理层级；年级部需要绑定对应年级与届别，学科组需要关联对应科目。
            </Paragraph>
            <Image
              src="/tutorial/personnel-organization.png"
              alt="创建组织架构"
              style={{ borderRadius: 8, marginBottom: 24, width: '100%' }}
              preview
            />
            <Alert
              type="info"
              showIcon
              message="人员分配关系说明"
              description="左侧组织树用于切换查看范围；右侧人员可以同时加入学科教研组和对应年级部。岗位职责在人员编辑中配置，账号状态可在列表中直接启用或停用。"
              style={{ marginBottom: 24 }}
            />
            <Title level={4}>2.2 新增人员账号</Title>
            <Paragraph>
              点击「新增人员」，填写姓名、登录手机号和初始密码，选择人员类型、岗位角色及所属组织。教师账号还需要选择教师职级；同一人员可以同时加入学科教研组和一个年级部。
            </Paragraph>
            <Image
              src="/tutorial/personnel-account-create.png"
              alt="新增人员"
              style={{ borderRadius: 8, width: '100%' }}
              preview
            />
          </div>
          <Divider />
          <div id="doc-settings">
            <Title level={3}>三、系统设置</Title>
            <Paragraph>在「系统设置」中配置学年学期、作息时间、节次安排等基础参数。</Paragraph>
          </div>
          <Divider />
          <div id="doc-faq">
            <Title level={3}>四、常见问题</Title>
            <Paragraph><b>Q: 如何添加教师？</b></Paragraph>
            <Paragraph>A: 在「人员账号」中点击「新增人员」，填写基本信息并分配岗位。</Paragraph>
            <Paragraph><b>Q: 排课冲突怎么办？</b></Paragraph>
            <Paragraph>A: 系统会自动检测时间、教室、教师冲突，并给出提示。可手动调整或使用自动排课功能。</Paragraph>
          </div>
        </Content>
      </Layout>
    </div>
  )
}
