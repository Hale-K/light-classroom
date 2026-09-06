import { useNavigate } from 'react-router-dom'
import Icon from '@/components/Icon'

interface TeacherModulePlaceholderProps {
  icon: string
  title: string
  description: string
}

/** Placeholder shown while a teacher module has no dedicated data workflow yet. */
export default function TeacherModulePlaceholder({ icon, title, description }: TeacherModulePlaceholderProps) {
  const navigate = useNavigate()

  return (
    <main className="td-module-placeholder">
      <div className="td-module-placeholder-icon"><Icon name={icon} size={34} /></div>
      <h1>{title}</h1>
      <p>{description}</p>
      <button type="button" onClick={() => navigate('/dashboard')}>返回首页</button>
    </main>
  )
}
