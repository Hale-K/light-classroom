import { NavLink } from 'react-router-dom'

const ITEMS = [
  { path: '/exam-venues', title: '考场安排', note: '确定本次使用范围' },
  { path: '/exam-calendar', title: '考试日程', note: '设置日期与考试场次' },
  { path: '/exam-invigilators', title: '监考教师', note: '设置可用、休假与排除' },
  { path: '/exam-scheduling', title: '人员排考', note: '查看考生与监考安排' },
]

export default function ExamModuleNav() {
  return <nav className="es-nav" aria-label="排考模块导航">
    {ITEMS.map((item) => <NavLink key={item.path} to={item.path} className={({ isActive }) => isActive ? 'active' : ''}>
      {item.title}<span>{item.note}</span>
    </NavLink>)}
  </nav>
}
