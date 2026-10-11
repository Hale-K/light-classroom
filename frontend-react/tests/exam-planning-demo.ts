import { http } from '../src/api/http'

// Isolated browser fixture: this adapter never writes to the school database.
export function installPlanningDemo() {
  let rules = { student_daily_limit: 2, min_break_minutes: 30, teacher_daily_limit: 2, avoid_own_subject: false, same_subject_same_time: true }
  const config = { exam_id: 2, grade_ids: [1, 2], subject_ids: [1, 2], start_date: '2026-10-12', candidate_mode: 'grade', schedule_mode: 'custom', excluded_dates: [], sessions: [{ start_time: '09:00', end_time: '11:00' }, { start_time: '14:00', end_time: '16:00' }], invigilators_per_room: 1 }
  const staff = ['王老师', '李老师', '陈老师', '赵老师'].map((name, i) => ({ teacher_id: i + 1, teacher_name: name, account_status: 'active', enabled: true, unavailable_slots: [], assigned_count: 1 }))
  const rooms = Array.from({ length: 6 }, (_, i) => ({ id: i + 11, exam_id: 2, exam_name: '高一期中考试', exam_schedule_id: i < 3 ? 1 : 2, invigilator_ids: [i % 3 + 1], invigilator_names: [staff[i % 3].teacher_name], grade_id: i === 2 || i === 5 ? 2 : 1, grade_name: i === 2 || i === 5 ? '高二' : '高一', subject_id: i < 3 ? 1 : 2, subject_name: i < 3 ? '数学' : '英语', exam_date: '2026-10-12', session_index: i < 3 ? 1 : 2, start_time: i < 3 ? '09:00' : '14:00', end_time: i < 3 ? '11:00' : '16:00', room_name: ['101教室', '102教室', '103教室'][i % 3], capacity: 40, candidate_count: i % 3 === 2 ? 32 : 40 }))
  const schedules = [1, 2].flatMap(grade => [1, 2].map(subject => ({ id: (grade - 1) * 2 + subject, exam_id: 2, exam_name: '高一期中考试', grade_id: grade, grade_name: grade === 1 ? '高一' : '高二', subject_id: subject, subject_name: subject === 1 ? '数学' : '英语', exam_date: '2026-10-12', session_index: subject, start_time: subject === 1 ? '09:00' : '14:00', end_time: subject === 1 ? '11:00' : '16:00', room: '已确认考场' })))
  rooms.forEach(room => { room.exam_schedule_id = (room.grade_id - 1) * 2 + room.subject_id })
  const other = { ...rooms[0], id: 101, exam_id: 1, exam_name: '高三模拟考试', exam_schedule_id: 101, grade_id: 3, grade_name: '高三', subject_name: '语文', start_time: '10:00', end_time: '12:00', candidate_count: 38 }
  const candidates = [{ id: 1, student_id: 1, exam_schedule_id: 1, exam_room_assignment_id: 11, grade_id: 1, subject_id: 1, student_name: '张同学', student_no: '2026001', grade_name: '高一', subject_name: '数学', exam_date: '2026-10-12', start_time: '09:00', end_time: '11:00', room_name: '101教室', seat_no: 1 }]
  const plan = () => ({ mode: 'custom', schedules, rooms, summary: { day_count: 1, session_count: 4, room_count: 6, student_count: 112, candidate_assignment_count: 224, invigilator_count: 3 } })
  http.defaults.adapter = async request => {
    const path = request.url || ''
    const body = typeof request.data === 'string' ? JSON.parse(request.data) : request.data
    let data: unknown = {}
    if (path === '/exams') data = [{ id: 2, name: '高一期中考试', status: 'preparing', academic_year: '2026-2027', term: '1' }]
    else if (path.endsWith('/grades')) data = [{ id: 1, name: '高一' }, { id: 2, name: '高二' }]
    else if (path.endsWith('/config')) { if (body?.rules) rules = body.rules; data = { ...config, rules } }
    else if (path.endsWith('/subjects')) data = [{ id: 1, name: '数学', grade_ids: [1, 2] }, { id: 2, name: '英语', grade_ids: [1, 2] }]
    else if (path === '/exam-scheduling/rooms') data = { items: ['101教室', '102教室', '103教室', '104教室'].map((name, i) => ({ id: i + 1, name, capacity: 40, status: 'available', room_type: 'standard' })), pagination: { total: 4, total_pages: 1 } }
    else if (path.endsWith('/venues')) data = { confirmed: true, rooms: ['101教室', '102教室', '103教室', '104教室'].map(name => ({ name, capacity: 40 })), summary: { room_count: 4, seat_count: 160 } }
    else if (path.endsWith('/invigilators')) data = staff
    else if (path.endsWith('/preview')) data = schedules
    else if (path.endsWith('/overview')) data = { schedules: [...schedules, { ...schedules[0], ...other, id: 101 }], rooms: [...rooms, other], venues: ['101教室', '102教室', '103教室', '104教室'].map(name => ({ name, capacity: 40, status: 'available' })), teachers: staff.map(t => ({ id: t.teacher_id, name: t.teacher_name })), rules }
    else if (path.endsWith('/checks')) data = { ok: false, issues: [{ code: 'teacher_collision', message: '王老师在 09:00–11:00 与高三模拟考试的监考时间重叠', suggestion: '更换空闲教师或调整考试时间', room_assignment_id: 11 }] }
    else if (path.endsWith('/plans/check')) data = { ok: true, student_count: 112, room_count: 6, session_count: 4 }
    else if (path.endsWith('/plans') || /\/plans\/\d+$/.test(path)) data = plan()
    else if (/\/rooms\/\d+$/.test(path)) {
      const room = rooms.find(r => r.id === Number(path.split('/').at(-1)))!
      if (body?.room_name) room.room_name = body.room_name
      if (body?.invigilator_ids) { room.invigilator_ids = body.invigilator_ids; room.invigilator_names = staff.filter(t => room.invigilator_ids.includes(t.teacher_id)).map(t => t.teacher_name) }
      data = room
    } else if (path.endsWith('/candidates')) data = { items: candidates, pagination: { page: 1, total: 1, total_pages: 1 } }
    return { data: { code: 0, data }, status: 200, statusText: 'OK', headers: {}, config: request }
  }
}
