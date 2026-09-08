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
              在「人员账号」中点击「新建组织」，选择组织类型并填写名称。年级部需挂到「年级管理中心」下，学科组需关联对应科目。
            </Paragraph>
            <Image
              src="https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=A%20clean%20modern%20education%20management%20system%20screenshot%20showing%20organization%20tree%20with%20departments%20and%20grade%20levels%2C%20light%20theme%2C%20Chinese%20UI&image_size=landscape_16_9"
              alt="创建组织架构"
              style={{ borderRadius: 8, marginBottom: 24, width: '100%' }}
              preview={false}
            />
            <Title level={4}>2.2 新增人员账号</Title>
            <Paragraph>
              点击「新增人员」，填写教师基本信息并分配岗位职责，如班主任、任课教师等。
            </Paragraph>
            <Image
              src="https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image?prompt=A%20clean%20modern%20education%20management%20system%20screenshot%20showing%20add%20staff%20account%20form%20modal%20with%20name%20phone%20role%20fields%2C%20light%20theme%2C%20Chinese%20UI&image_size=landscape_16_9"
              alt="新增人员"
              style={{ borderRadius: 8, width: '100%' }}
              preview={false}
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
