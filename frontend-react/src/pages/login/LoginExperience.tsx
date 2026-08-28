import { Button, Form, Input } from 'antd'
import Icon from '@/components/Icon'
import { APP_NAME } from '@/types'
import './login-experience.css'

export interface LoginExperienceForm {
  phone: string
  password: string
}

interface LoginExperienceProps {
  submitting: boolean
  onSubmit: (values: LoginExperienceForm) => void
}

export default function LoginExperience({ submitting, onSubmit }: LoginExperienceProps) {
  return (
    <main className="login-experience" aria-label="轻课堂登录">
      <section className="login-experience__intro" aria-labelledby="login-intro-title">
        <div className="login-experience__intro-inner">
          <div className="login-experience__brand">
            <span className="login-experience__brand-mark">轻</span>
            <span>
              <strong>{APP_NAME}</strong>
              <small>轻课堂教务系统</small>
            </span>
          </div>

          <div className="login-experience__message">
            <p className="login-experience__eyebrow">SCHOOL OPERATIONS / 01</p>
            <h1 id="login-intro-title">让每一次教学安排，<em>有据可循。</em></h1>
            <p className="login-experience__lead">
              从排课、排考到班级与座位管理，把学校每天发生的复杂事务，收拢成清晰可执行的工作流。
            </p>
          </div>

          <div className="login-experience__signals" aria-label="系统能力">
            <div><b>01</b><span>统一教务工作台</span></div>
            <div><b>02</b><span>按学校隔离数据</span></div>
            <div><b>03</b><span>全流程留痕可追溯</span></div>
          </div>

          <p className="login-experience__edition">EDUCATION MANAGEMENT PLATFORM · 2026</p>
        </div>
      </section>

      <section className="login-experience__form-side" aria-labelledby="login-form-title">
        <div className="login-experience__form-wrap">
          <div className="login-experience__form-heading">
            <span className="login-experience__section-index">WORKSPACE ACCESS</span>
            <h2 id="login-form-title">登录工作台</h2>
            <p>使用学校分配的账号继续工作。</p>
          </div>

          <Form<LoginExperienceForm> layout="vertical" requiredMark={false} onFinish={onSubmit}>
            <Form.Item
              name="phone"
              label="手机号"
              rules={[
                { required: true, message: '请输入手机号' },
                { pattern: /^1\d{10}$/, message: '手机号格式不正确' },
              ]}
            >
              <Input
                size="large"
                prefix={<Icon name="users" size={16} />}
                placeholder="请输入手机号"
                maxLength={11}
                autoFocus
              />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password size="large" prefix={<Icon name="keyboard" size={16} />} placeholder="请输入密码" />
            </Form.Item>
            <Button className="login-experience__submit" type="primary" htmlType="submit" block size="large" loading={submitting}>
              进入工作台
              <Icon name="arrow-right" size={16} />
            </Button>
          </Form>

          <div className="login-experience__trust">
            <span><i />学校数据隔离</span>
            <span><i />私有化部署</span>
            <span><i />操作全程留痕</span>
          </div>
          <p className="login-experience__copyright">{APP_NAME} · 轻课堂 <span>© 2026</span></p>
        </div>
      </section>
    </main>
  )
}
