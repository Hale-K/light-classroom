import { useEffect, useMemo, useState } from 'react'
import { Button, Input, Pagination, Select, Spin } from 'antd'
import { gsap } from 'gsap'
import DictTag from '@/components/DictTag'
import EmptyState from '@/components/EmptyState'
import { EXAM_STATUS_DICT, EXAM_TYPE_DICT, PAPER_STATUS_DICT } from '@/types/dict'
import type { Exam, Grade, Paper } from '@/types'

export const PAPER_SUBJECTS = [
  { id: 1, name: '语文', tone: '#9b413f' },
  { id: 2, name: '数学', tone: '#275aa8' },
  { id: 3, name: '英语', tone: '#6650a4' },
  { id: 4, name: '物理', tone: '#236477' },
  { id: 5, name: '化学', tone: '#3d7560' },
  { id: 6, name: '生物', tone: '#58703b' },
  { id: 7, name: '政治', tone: '#a45138' },
  { id: 8, name: '历史', tone: '#816239' },
  { id: 9, name: '地理', tone: '#47726e' },
]

interface PaperLibraryProps {
  exams: Exam[]
  papersByExam: Record<number, Paper[]>
  loading: boolean
  onOpenPaper: (paper: Paper, exam: Exam) => void
  onCreatePaper: (exam: Exam) => void
  onCreateExam: () => void
  grades: Grade[]
}

function subjectOf(paper: Paper) {
  return PAPER_SUBJECTS.find((subject) => subject.id === paper.subject_id)
}

function PaperBook({ paper, exam, onOpen }: { paper: Paper; exam: Exam; onOpen: () => void }) {
  const subject = subjectOf(paper)
  const seed = paper.id * 17 + (paper.title?.length || 0) * 7
  const height = 164 + (seed % 4) * 9
  const width = 44 + (seed % 3) * 5

  const extractBook = (event: React.MouseEvent<HTMLButtonElement>) => {
    const element = event.currentTarget
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      onOpen()
      return
    }
    gsap.killTweensOf(element)
    gsap.timeline({ onComplete: onOpen })
      .to(element, { y: -16, z: 28, rotateY: -5, duration: 0.3, ease: 'power2.out' })
      .to(element, { x: 8, y: -10, z: 46, rotateY: -17, duration: 0.28, ease: 'power2.inOut' })
  }

  return (
    <button
      type="button"
      className="zh-library-book"
      style={{
        '--book-height': `${height}px`,
        '--book-width': `${width}px`,
        '--book-tone': subject?.tone || '#46576f',
      } as React.CSSProperties}
      onClick={extractBook}
      aria-label={`打开试卷：${paper.title}`}
      title={`${paper.title} · ${subject?.name || '未设置科目'}`}
    >
      <span className="zh-library-book-pages" aria-hidden="true" />
      <span className="zh-library-book-spine">
        <span className="zh-library-book-subject">{subject?.name || '综合'}</span>
        <span className="zh-library-book-title">{paper.title}</span>
        <span className="zh-library-book-mark">{paper.status === 'finalized' ? '定稿' : '编制'}</span>
      </span>
      <span className="zh-library-book-cover" aria-hidden="true">
        <small>{subject?.name || '综合'}试卷</small>
        <strong>{paper.title}</strong>
        <span>{exam.academic_year || '校本试卷库'}</span>
      </span>
    </button>
  )
}

export default function PaperLibrary({
  exams,
  papersByExam,
  loading,
  onOpenPaper,
  onCreatePaper,
  onCreateExam,
  grades,
}: PaperLibraryProps) {
  const [keyword, setKeyword] = useState('')
  const [subjectId, setSubjectId] = useState<number | undefined>()
  const [paperStatus, setPaperStatus] = useState<string | undefined>()
  const [cohortFilter, setCohortFilter] = useState<string | undefined>()
  const [gradeFilter, setGradeFilter] = useState<number | undefined>()
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>()
  const [page, setPage] = useState(1)
  const [appliedFilters, setAppliedFilters] = useState({
    keyword: '',
    subjectId: undefined as number | undefined,
    paperStatus: undefined as string | undefined,
    cohortFilter: undefined as string | undefined,
    gradeFilter: undefined as number | undefined,
    categoryFilter: undefined as string | undefined,
  })

  const gradeMap = useMemo(() => new Map(grades.map((grade) => [grade.id, grade])), [grades])
  const cohortOf = (exam: Exam, paper?: Paper) => {
    const startYear = Number((exam.academic_year || '').slice(0, 4))
    const level = paper?.grade_id ? gradeMap.get(paper.grade_id)?.level : undefined
    return Number.isFinite(startYear) && level ? `${startYear + 4 - level}届` : undefined
  }
  const cohortOptions = useMemo(() => Array.from(new Set(
    exams.flatMap((exam) => (papersByExam[exam.id] || []).map((paper) => cohortOf(exam, paper)).filter(Boolean) as string[]),
  )).sort().map((value) => ({ label: value, value })), [exams, gradeMap, papersByExam])
  const gradeOptions = useMemo(() => grades.map((grade) => ({ label: grade.name, value: grade.id })), [grades])
  const categoryOptions = useMemo(() => Array.from(new Set(exams.map((exam) => exam.exam_type).filter(Boolean))).map((value) => ({ label: EXAM_TYPE_DICT[value!]?.label || value!, value: value! })), [exams])

  const applyFilters = () => {
    setAppliedFilters({ keyword: keyword.trim(), subjectId, paperStatus, cohortFilter, gradeFilter, categoryFilter })
    setPage(1)
  }
  const resetFilters = () => {
    setKeyword(''); setSubjectId(undefined); setPaperStatus(undefined); setCohortFilter(undefined); setGradeFilter(undefined); setCategoryFilter(undefined)
    setAppliedFilters({ keyword: '', subjectId: undefined, paperStatus: undefined, cohortFilter: undefined, gradeFilter: undefined, categoryFilter: undefined })
    setPage(1)
  }

  const shelves = useMemo(() => {
    const normalizedKeyword = appliedFilters.keyword.toLocaleLowerCase()
    return exams
      .map((exam) => ({
        exam,
        papers: (papersByExam[exam.id] || []).filter((paper) => {
          const subject = subjectOf(paper)?.name || ''
          const matchesKeyword =
            !normalizedKeyword ||
            `${paper.title} ${exam.name} ${subject}`.toLocaleLowerCase().includes(normalizedKeyword)
          return (
            matchesKeyword &&
            (!appliedFilters.subjectId || paper.subject_id === appliedFilters.subjectId) &&
            (!appliedFilters.paperStatus || paper.status === appliedFilters.paperStatus) &&
            (!appliedFilters.gradeFilter || paper.grade_id === appliedFilters.gradeFilter) &&
            (!appliedFilters.cohortFilter || cohortOf(exam, paper) === appliedFilters.cohortFilter) &&
            (!appliedFilters.categoryFilter || exam.exam_type === appliedFilters.categoryFilter)
          )
        }),
      }))
      .filter(({ papers }) => papers.length > 0 || (!appliedFilters.keyword && !appliedFilters.subjectId && !appliedFilters.paperStatus && !appliedFilters.gradeFilter && !appliedFilters.cohortFilter && !appliedFilters.categoryFilter))
  }, [appliedFilters, exams, gradeMap, papersByExam])

  const visibleCount = shelves.reduce((count, shelf) => count + shelf.papers.length, 0)
  const pageSize = 3
  const pagedShelves = shelves.slice((page - 1) * pageSize, page * pageSize)

  useEffect(() => {
    setPage(1)
  }, [appliedFilters])

  return (
    <section className="zh-library" aria-label="试卷图书馆">
      <div className="zh-library-searchbar">
        <div className="zh-library-search-copy">
          <span className="zh-library-kicker">PAPER ARCHIVE</span>
          <strong>{visibleCount} 本试卷</strong>
        </div>
        <Input.Search
          allowClear
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          onSearch={() => applyFilters()}
          placeholder="搜索试卷、考试或学科"
          className="zh-library-search"
        />
        <Select
          allowClear
          value={subjectId}
          onChange={setSubjectId}
          placeholder="全部学科"
          options={PAPER_SUBJECTS.map((subject) => ({ label: subject.name, value: subject.id }))}
          className="zh-library-filter"
        />
        <Select allowClear value={cohortFilter} onChange={setCohortFilter} placeholder="全部届别" options={cohortOptions} className="zh-library-filter" />
        <Select allowClear value={gradeFilter} onChange={setGradeFilter} placeholder="全部年级" options={gradeOptions} className="zh-library-filter" />
        <Select allowClear value={categoryFilter} onChange={setCategoryFilter} placeholder="全部分类" options={categoryOptions} className="zh-library-filter" />
        <Select
          allowClear
          value={paperStatus}
          onChange={setPaperStatus}
          placeholder="全部状态"
          options={Object.entries(PAPER_STATUS_DICT).map(([value, item]) => ({
            label: item.label,
            value,
          }))}
          className="zh-library-filter"
        />
        <Button type="primary" onClick={applyFilters}>查询</Button>
        <Button onClick={resetFilters}>重置</Button>
      </div>

      {loading ? (
        <div className="zh-library-loading"><Spin tip="正在整理书架" /></div>
      ) : shelves.length === 0 ? (
        <EmptyState
          icon="file-text"
          title="没有找到试卷"
          desc="换一个搜索条件，或先创建一场考试并开始建卷"
          height={280}
          actionText="新建考试"
          onAction={onCreateExam}
        />
      ) : (
        <>
        <div className="zh-library-shelves">
          {pagedShelves.map(({ exam, papers }) => (
            <article key={exam.id} className="zh-library-shelf">
              <header className="zh-library-shelf-head">
                <div>
                  <span className="zh-library-shelf-year">{exam.academic_year || '未设置学年'}</span>
                  <h2>{exam.name}</h2>
                  <small className="zh-library-shelf-context">
                    {cohortOf(exam, papers[0]) || '未设置届别'} · {papers[0]?.grade_id ? gradeMap.get(papers[0].grade_id)?.name || '未设置年级' : '未设置年级'} · {EXAM_TYPE_DICT[exam.exam_type || '']?.label || '其他'}
                  </small>
                </div>
                <div className="zh-library-shelf-meta">
                  <DictTag dict={EXAM_STATUS_DICT} value={exam.status} />
                  <span>{papers.length} 本</span>
                  {exam.status === 'preparing' && (
                    <Button type="link" onClick={() => onCreatePaper(exam)}>新增试卷</Button>
                  )}
                </div>
              </header>

              <div className="zh-library-shelf-stage">
                {papers.length ? (
                  <div className="zh-library-books">
                    {papers.map((paper) => (
                      <PaperBook
                        key={paper.id}
                        paper={paper}
                        exam={exam}
                        onOpen={() => onOpenPaper(paper, exam)}
                      />
                    ))}
                  </div>
                ) : (
                  <button type="button" className="zh-library-empty-slot" onClick={() => onCreatePaper(exam)}>
                    <span>＋</span>
                    这层书架还没有试卷，点击开始建卷
                  </button>
                )}
                <div className="zh-library-shelf-board" aria-hidden="true" />
              </div>
            </article>
          ))}
        </div>
        {shelves.length > pageSize && <div className="zh-library-pagination"><Pagination current={page} pageSize={pageSize} total={shelves.length} showSizeChanger={false} showTotal={(total) => `共 ${total} 个书架`} onChange={setPage} /></div>}
        </>
      )}
    </section>
  )
}
