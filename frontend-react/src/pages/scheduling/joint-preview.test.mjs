import test from 'node:test'
import assert from 'node:assert/strict'
import { selectPreviewLessons, filterPreviewStudents, primaryClassLabel, summarizeTeacherWorkload } from './joint-preview.ts'

test('student preview combines only their administrative and new teaching classes', () => {
  const lessons = [
    {kind:'admin',class_id:101}, {kind:'admin',class_id:102},
    {kind:'walk',class_id:8}, {kind:'walk',class_id:9}, {kind:'walk',class_id:10},
  ]
  assert.deepEqual(selectPreviewLessons(lessons, 'student', 1,
    [{id:1,class_id:101,teaching_class_ids:[8,9]}]), [lessons[0], lessons[2], lessons[3]])
  assert.deepEqual(selectPreviewLessons(lessons, 'student', 99, []), [])
})

test('class and trimmed student name filters combine without changing input', () => {
  const students = [{id:1,name:'小明',class_id:101}, {id:2,name:'小明',class_id:102},
    {id:3,name:'小红',class_id:101}]
  assert.deepEqual(filterPreviewStudents(students,101,' 明 '),[students[0]])
  assert.deepEqual(filterPreviewStudents(students,undefined,'小明'),students.slice(0,2))
  assert.deepEqual(filterPreviewStudents(students,101,'不存在'),[])
  assert.equal(students.length,3)
})
test('class direction comes from actual confirmed selections and supports mixed classes', () => {
  const students = [{class_id:101,primary_subject_name:'物理'},
    {class_id:102,primary_subject_name:'历史'}, {class_id:103,primary_subject_name:'物理'},
    {class_id:103,primary_subject_name:'历史'}]
  assert.equal(primaryClassLabel(students,101),'物理班')
  assert.equal(primaryClassLabel(students,102),'历史班')
  assert.equal(primaryClassLabel(students,103),'物理／历史混合班')
  assert.equal(primaryClassLabel(students,104),'首选科目未提供')
})
test('administrative and teaching views do not mix classes or kinds', () => {
  const lessons = [{kind:'admin',class_id:8}, {kind:'walk',class_id:8}, {kind:'walk',class_id:9}]
  assert.deepEqual(selectPreviewLessons(lessons,'admin',8,[]),[lessons[0]])
  assert.deepEqual(selectPreviewLessons(lessons,'walk',8,[]),[lessons[1]])
})

test('teacher workload compares actual lesson counts against the grade average', () => {
  const lessons = [
    ...Array.from({length: 5}, () => ({teacher_id:1,teacher_name:'张老师',subject_name:'政治',kind:'walk'})),
    ...Array.from({length: 3}, () => ({teacher_id:2,teacher_name:'李老师',subject_name:'政治',kind:'admin'})),
    {teacher_id:2,teacher_name:'李老师',subject_name:'语文',kind:'admin'},
  ]
  assert.deepEqual(summarizeTeacherWorkload(lessons), [
    {teacher_id:1,teacher_name:'张老师',subject_name:'政治',admin:0,walk:5,total:5,subject_total:8,difference:1},
    {teacher_id:2,teacher_name:'李老师',subject_name:'政治',admin:3,walk:0,total:3,subject_total:8,difference:-1},
    {teacher_id:2,teacher_name:'李老师',subject_name:'语文',admin:1,walk:0,total:1,subject_total:1,difference:0},
  ])
  assert.deepEqual(summarizeTeacherWorkload(lessons,'政治'), [
    {teacher_id:1,teacher_name:'张老师',subject_name:'政治',admin:0,walk:5,total:5,subject_total:8,difference:1},
    {teacher_id:2,teacher_name:'李老师',subject_name:'政治',admin:3,walk:0,total:3,subject_total:8,difference:-1},
  ])
  assert.deepEqual(summarizeTeacherWorkload([]), [])
})
