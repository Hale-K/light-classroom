import { authApi, schedulingApi, teacherProfilesApi } from '@/api'

export type AssistantTool = 'openScheduling' | 'checkTeachers' | 'checkSettings'

export async function runAssistantTool(tool: AssistantTool, path?: string): Promise<{ path: string; report: string }> {
  if (tool === 'openScheduling') {
    const years = await authApi.academicYears()
    const year = years.current_academic_year
    const term = years.current_term || '1'
    let gridLine = '网格未读到（先配学年学期）'
    if (year) {
      try {
        const grid = await schedulingApi.gridConfig({ academic_year: year, term })
        gridLine = `网格 ${grid.days} 天 × ${grid.periods_per_day} 节${grid.enable_evening ? '，含晚自习' : ''}`
      } catch {
        gridLine = '网格尚未配置，请在「时间结构」里保存'
      }
    }
    return {
      path: path || '/scheduling?tab=rules',
      report: `已打开排课。当前学年 ${year || '未设'}，第 ${term} 学期。${gridLine}。请人工核对规则后再点生成，我不会代跑求解器。`,
    }
  }
  if (tool === 'checkTeachers') {
    const meta = await teacherProfilesApi.filters()
    const year = meta.defaults?.academic_year || null
    const term = meta.defaults?.term || '1'
    const list = await teacherProfilesApi.list({
      academic_year: year,
      term,
    })
    const ratio = list.class_summary
      ? Math.round(list.class_summary.completion_ratio)
      : 0
    const target = list.class_summary?.weekly_target ?? 0
    const scheduled = list.class_summary?.scheduled_lessons ?? 0
    return {
      path: '/teacher-profiles',
      report: `已打开教师档案。${year || '当前学年'} · 第${term}学期，完成度 ${ratio}%（已排 ${scheduled} / 目标 ${target}）。按课时网格核算，停用教师不进列表。`,
    }
  }
  const years = await authApi.academicYears()
  const year = years.current_academic_year
  const term = years.current_term || '1'
  let gridLine = '还没有网格，排课容量未知'
  if (year) {
    try {
      const grid = await schedulingApi.gridConfig({ academic_year: year, term })
      gridLine = `网格 ${grid.days}×${grid.periods_per_day}${grid.enable_evening ? ' 含晚自习' : ''}`
    } catch {
      gridLine = '网格未保存'
    }
  }
  return {
    path: '/settings',
    report: `已打开系统设置。学年 ${year || '未设置'}，学期 ${term}。${gridLine}。我不会替你保存或滚动学年。`,
  }
}
