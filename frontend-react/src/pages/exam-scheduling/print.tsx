import { useEffect, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import type { AdmissionTicket, ExamRoomAssignment } from '@/types'

export function TicketDocument({ school, exam, tickets }: { school: string; exam: string; tickets: AdmissionTicket[] }) {
  return <>{tickets.map(ticket => <article className="exam-print-sheet" key={ticket.student_id}>
    <div className="exam-print-school">{school}</div><h1>{exam} · 准考证</h1>
    <div className="exam-print-identity"><div><p>姓名：<strong>{ticket.student_name}</strong></p><p>年级 / 班级：{ticket.grade_name} {ticket.class_name}</p><p>学号：{ticket.student_no || '—'}</p><p>准考证号：{ticket.candidate_no}</p></div><div className="exam-print-photo">照片</div></div>
    <table><thead><tr><th>科目</th><th>日期</th><th>时间</th><th>考场</th><th>座位</th></tr></thead><tbody>{ticket.sessions.map((s, i) => <tr key={i}><td>{s.subject_name}</td><td>{s.exam_date}</td><td>{s.start_time}–{s.end_time}</td><td>{s.room_name}</td><td>{s.seat_no}</td></tr>)}</tbody></table>
    <p className="exam-print-note">请核对考试时间、考场和座位，携带准考证参加考试。</p>
  </article>)}</>
}

export function DutyDocument({ exam, rooms }: { exam: string; rooms: ExamRoomAssignment[] }) {
  const teachers = [...new Map(rooms.flatMap(r => r.invigilator_ids.map((id, i) => [id, r.invigilator_names[i]] as const))).entries()]
  return <>{teachers.map(([id, name]) => <article key={id} className="exam-print-sheet"><h1>{exam} · 监考任务单</h1><h2>{name}</h2><table><thead><tr><th>日期</th><th>时间</th><th>科目 / 年级</th><th>考场</th><th>人数</th></tr></thead><tbody>{rooms.filter(r => r.invigilator_ids.includes(id)).map(r => <tr key={r.id}><td>{r.exam_date}</td><td>{r.start_time}–{r.end_time}</td><td>{r.subject_name} / {r.grade_name}</td><td>{r.room_name}</td><td>{r.candidate_count}</td></tr>)}</tbody></table></article>)}</>
}

export function ResourceDocument({ exam, rooms }: { exam: string; rooms: ExamRoomAssignment[] }) {
  return <article className="exam-print-sheet"><h1>{exam} · 考场使用表</h1><table><thead><tr><th>日期 / 时间</th><th>考场</th><th>科目 / 年级</th><th>人数 / 容量</th><th>监考教师</th></tr></thead><tbody>{rooms.map(r => <tr key={r.id}><td>{r.exam_date}<br />{r.start_time}–{r.end_time}</td><td>{r.room_name}</td><td>{r.subject_name} / {r.grade_name}</td><td>{r.candidate_count} / {r.capacity}</td><td>{r.invigilator_names.join('、')}</td></tr>)}</tbody></table></article>
}

const PRINT_CSS = `@page { size: A4; margin: 15mm; } * { box-sizing: border-box; } body { margin: 0; color: #111; font: 14px/1.6 'Microsoft YaHei', sans-serif; }
.exam-print-sheet { break-after: page; padding: 12px; } .exam-print-sheet:last-child { break-after: auto; } h1 { text-align: center; font-size: 23px; margin: 12px 0 28px; } h2 { font-size: 18px; } .exam-print-school { text-align: center; font-size: 15px; }
.exam-print-identity { display: flex; justify-content: space-between; margin-bottom: 26px; gap: 20px; } .exam-print-photo { width: 28mm; height: 36mm; border: 1px solid #888; display: grid; place-items: center; color: #888; flex-shrink: 0; } p { margin: 8px 0; } table { border-collapse: collapse; width: 100%; table-layout: fixed; } th, td { border: 1px solid #777; padding: 10px 6px; text-align: center; overflow-wrap: anywhere; } thead { display: table-header-group; } tr { break-inside: avoid; } .exam-print-note { margin-top: 24px; font-size: 12px; }`

/** Use a separate print document; React escapes every value from API data. */
export async function printExamDocument(title: string, content: ReactNode) {
  const frame = document.createElement('iframe')
  frame.title = title; frame.setAttribute('aria-hidden', 'true')
  frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:794px;height:1123px;border:0'
  document.body.appendChild(frame)
  const doc = frame.contentDocument
  if (!doc || !frame.contentWindow) { frame.remove(); throw new Error('无法打开打印预览') }
  doc.title = title
  const style = doc.createElement('style'); style.textContent = PRINT_CSS; doc.head.appendChild(style)
  const root = createRoot(doc.body)
  const cleanup = () => { root.unmount(); frame.remove() }
  frame.contentWindow.addEventListener('afterprint', cleanup, { once: true })
  await new Promise<void>((resolve, reject) => {
    function Ready() {
      useEffect(() => {
        void (async () => {
          try { await doc!.fonts.ready; await new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r())))
            frame.contentWindow!.focus(); frame.contentWindow!.print(); resolve()
          } catch (e) { cleanup(); reject(e) }
        })()
      }, [])
      return <>{content}</>
    }
    root.render(<Ready />)
  })
}
