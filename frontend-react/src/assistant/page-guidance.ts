export type PageGuidance = {
  match: string
  title: string
  summary: string
  steps: string[]
}

const GUIDES: PageGuidance[] = [
  { match: '/dashboard', title: '工作台', summary: '查看当前账号的教务概览和待办。', steps: ['先看异常和未完成指标', '从快捷入口进入对应业务页', '处理后返回刷新结果'] },
  { match: '/onboarding', title: '新手引导', summary: '按学校初始化顺序完成基础数据。', steps: ['核对当前待办', '点「去完成」进入页面', '处理后回来刷新进度'] },
  { match: '/settings', title: '系统设置', summary: '维护当前学年、学期、届次和年级基础数据。', steps: ['确认当前学年学期', '维护届次与年级', '再配置人员、空间和班级'] },
  { match: '/staff', title: '人员账号', summary: '维护学校组织、人员账号及组织归属。', steps: ['先选择组织范围', '新增或导入人员', '核对账号状态和所属部门'] },
  { match: '/staff-positions', title: '岗位与权限', summary: '把人员安排到实际教务岗位。', steps: ['筛选人员', '分配岗位和职责范围', '保存后核对可用菜单'] },
  { match: '/rbac', title: '角色与权限', summary: '维护角色可见菜单和可执行操作。', steps: ['选择角色', '核对适用对象', '勾选权限并保存'] },
  { match: '/campus-buildings', title: '空间资源', summary: '建立空间、分配届别资源并据此规划行政班。', steps: ['建立校区、楼宇和场室', '创建并执行资源分配规则', '按已分配教室生成或绑定行政班'] },
  { match: '/students', title: '学生档案', summary: '维护学生基础资料和年级、班级归属。', steps: ['导入或新增学生', '处理未分班学生', '核对年级关联和档案状态'] },
  { match: '/classes', title: '行政班管理', summary: '维护班级、班主任和学生名单。', steps: ['选择年级并核对班级', '分配班主任和教室', '完成学生分班'] },
  { match: '/subjects', title: '科目管理', summary: '维护排课、考试和成绩共用的科目。', steps: ['检查是否已有同名科目', '新增或调整科目类型', '确认启用状态'] },
  { match: '/teacher-profiles', title: '教师档案', summary: '核对教师任教学科、班级和课时完成度。', steps: ['选择学年学期和学科', '查看任教与目标课时', '回到任教关系补齐缺项'] },
  { match: '/scheduling', title: '排课管理', summary: '从课时、课位、任教和规则生成课表。', steps: ['填班级课时并保存课位结构', '补齐任教关系和规则组', '校验后生成并检查课表'] },
  { match: '/gaokao', title: '学生选课', summary: '维护选科结果并规划教学班。', steps: ['选择年级和高考模式', '核对选科组合人数', '满足条件后生成教学班'] },
  { match: '/seating', title: '班级排座', summary: '按班级和规则生成座位方案。', steps: ['选择班级与排座规则', '设置需要分开或相邻的学生', '生成后检查并启用座位表'] },
  { match: '/exams', title: '试卷库', summary: '维护考试使用的试卷和题目结构。', steps: ['筛选或新建试卷', '核对题目和分值', '再进入扫描或阅卷'] },
  { match: '/scans', title: '扫描进卷', summary: '上传答卷并跟踪识别处理。', steps: ['选择试卷并建立批次', '上传扫描文件', '处理识别异常后进入阅卷'] },
  { match: '/exam-rooms', title: '考场管理', summary: '选择可用于考试的场室并核对容量。', steps: ['检查场室容量和状态', '启用本次可用考场', '继续设置考试使用范围'] },
  { match: '/exam-venues', title: '考场安排', summary: '为一次考试确定实际使用的考场。', steps: ['选择考试', '勾选考场并核对总容量', '保存后配置考试日程'] },
  { match: '/exam-calendar', title: '考试日程', summary: '设置考试日期、场次和科目时间。', steps: ['选择考试', '安排日期与场次', '检查时间重叠后保存'] },
  { match: '/exam-invigilators', title: '监考教师', summary: '维护本次考试可参与监考的教师。', steps: ['选择考试', '核对教师可用或请假状态', '保存后进入人员排考'] },
  { match: '/exam-scheduling', title: '排考管理', summary: '生成并检查考生考场与监考安排。', steps: ['确认考场、日程和教师已准备', '生成排考结果', '检查缺员、容量和冲突'] },
  { match: '/grading', title: '打分工作台', summary: '按题目查看答卷并提交评分。', steps: ['确认当前试卷和题号', '查看答卷并按标准评分', '保存后进入下一份'] },
  { match: '/stats', title: '成绩统计', summary: '查看考试成绩和各维度表现。', steps: ['确认统计范围和数据完整性', '查看班级与分数段分布', '定位需要复盘的题目或班级'] },
  { match: '/meetings', title: '会议管理', summary: '维护会议及其场室占用。', steps: ['选择会议时间和参与范围', '检查场室可用性', '保存后核对冲突'] },
  { match: '/file-center', title: '文件中心', summary: '查看导入导出后台任务和结果文件。', steps: ['按业务和状态筛选任务', '刷新查看处理进度', '完成后下载或查看失败明细'] },
  { match: '/ai-providers', title: '服务商管理', summary: '配置教务助手使用的大模型服务。', steps: ['新增服务商并填写模型', '测试连接', '成功后启用并设为默认'] },
]

export function pageGuidance(pathname: string): PageGuidance | null {
  return GUIDES
    .filter((guide) => pathname === guide.match || pathname.startsWith(`${guide.match}/`))
    .sort((left, right) => right.match.length - left.match.length)[0] ?? null
}

export function pageGuidanceText(pathname: string): string | null {
  const guide = pageGuidance(pathname)
  if (!guide) return null
  return `${guide.title}用于${guide.summary}\n${guide.steps.map((step, index) => `${index + 1}. ${step}`).join('\n')}\n如果你告诉我具体卡在哪一步，我会按当前页面继续说明。`
}
