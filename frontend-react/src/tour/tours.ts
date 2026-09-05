/** 本页导览：每个路由的分步说明。
 *  target 支持 CSS 选择器或返回元素的小函数（用于按文案找按钮）；
 *  页面没有定义导览时，顶栏不显示「本页导览」入口。
 *  beforeEnter 可在进入步骤前切换页签；目标在页签渲染后再解析。
 */

export type TourTarget = string | (() => Element | null)

export type TourStep = {
  title: string
  content: string
  target: TourTarget
  beforeEnter?: () => void | Promise<void>
}

const firstOf = (...selectors: string[]) => (): Element | null => {
  for (const selector of selectors) {
    const match = document.querySelector(selector)
    if (match) return match
  }
  return null
}

const tabByLabel = (containerSelector: string, label: string): HTMLElement | null => {
  const container = document.querySelector(containerSelector)
  if (!container) return null
  return [...container.querySelectorAll<HTMLElement>('[role="tab"]')]
    .find((tab) => tab.textContent?.trim().includes(label)) ?? null
}

const switchTab = (containerSelector: string, label: string) => () => {
  const tab = tabByLabel(containerSelector, label)
  if (tab?.getAttribute('aria-disabled') !== 'true' && tab?.getAttribute('aria-selected') !== 'true') {
    tab?.click()
  }
}

const tabPanelTarget = (containerSelector: string, label: string, ...panelSelectors: string[]) =>
  (): Element | null => firstOf(...panelSelectors)() ?? tabByLabel(containerSelector, label)

export const PAGE_TOURS: Record<string, TourStep[]> = {
  '/onboarding': [
    { title: '进度总览', content: '环上的数字是七步引导的实时完成度，状态全部来自本校真实数据，做完一步自动亮一格。', target: '.ob-banner' },
    { title: '当前待办', content: '按推荐顺序排的待办卡，点「去完成」直达对应页面；完成后回来点「刷新进度」。', target: '.ob-card' },
    { title: '已完成清单', content: '做过的事不会丢，每一步的摘要都在这里（没有待办时此卡不显示）。', target: '.ob-done-card' },
  ],
  '/dashboard': [
    { title: '今日工作台', content: '这里汇总当前账号最需要关注的教务信息；管理员看到学校概览，教师看到个人课表与待办。', target: firstOf('.wb-header', '.tw-header') },
    { title: '关键指标', content: '管理员可核对班级、课时、任教和规则覆盖；教师可查看今日课程、备忘和个人进度。', target: firstOf('.wb-metrics', '.tw-split') },
    { title: '快捷入口', content: '从这里直接进入对应工作页；进入后可再次打开本页导览查看具体操作。', target: firstOf('.wb-action-grid', '.tw-diamond-grid') },
  ],
  '/exams': [
    { title: '试卷筛选', content: '按学科、年级和关键词缩小试卷范围；筛选只改变当前列表，不会修改试卷内容。', target: '.zh-library-exam-filter' },
    { title: '试卷库', content: '点击试卷查看题目目录和基本信息；新建、编辑和删除操作都从试卷记录进入。', target: firstOf('.zh-library', '.ant-table-wrapper') },
  ],
  '/scans': [
    { title: '扫描批次筛选', content: '按试卷或处理状态查找扫描批次，先定位批次再查看识别和阅卷进度。', target: '.zh-filter-row' },
    { title: '扫描任务', content: '这里显示上传文件、识别数量和当前状态；进入批次后可继续核对异常答卷。', target: '.ant-table-wrapper' },
  ],
  '/scheduling': [
    {
      title: '先看完整排课流程',
      content: '排课按“课时管理 → 课位结构 → 任教关系 → 建立规则 → 课表”推进。导览会自动切换每个页签；你也可以随时返回前一步修改，后续结果会按最新配置重新计算。',
      target: firstOf('.sk-tabs .ant-tabs-nav-list', '.sk-tabs [role="tablist"]'),
    },
    {
      title: '确定每个班的课程总量',
      content: '先选择班级范围，再维护各科工作日、周六和晚课课时。这里决定算法必须排满多少节；晚课可用 0、0.5 或 1 表示单双周安排。',
      target: tabPanelTarget('.sk-tabs', '课时管理', '.sk-hours-intro', '.sk-hours'),
      beforeEnter: switchTab('.sk-tabs', '课时管理'),
    },
    {
      title: '逐科核对课时方案',
      content: '表格一行对应一个班级的一门科目。重点检查总课时、单双周和任课教师是否符合教学计划；遗漏的课时会让生成结果缺课。',
      target: tabPanelTarget('.sk-tabs', '课时管理', '.sk-hours-table', '.sk-hours'),
      beforeEnter: switchTab('.sk-tabs', '课时管理'),
    },
    {
      title: '定义一周有哪些可排课位',
      content: '分别设置每天正式课节数和单、双周特殊课位，然后保存。课位结构决定一周的容量，也是“建立规则”和“课表”两个页签的解锁条件。',
      target: tabPanelTarget('.sk-tabs', '课位结构', '.slot-structure-panel'),
      beforeEnter: switchTab('.sk-tabs', '课位结构'),
    },
    {
      title: '把课程分配给教师和教室',
      content: '按班级、学科、教师或教室筛选任教关系，也可以用“自动生成”建立基础关系。每个需要排课的班级与科目都应有明确教师；专用教室也在这里指定。',
      target: tabPanelTarget('.sk-tabs', '任教关系', '.sk-assign-filters', '.sk-assign'),
      beforeEnter: switchTab('.sk-tabs', '任教关系'),
    },
    {
      title: '检查任教关系是否完整',
      content: '逐行核对班级、科目、教师、教室和课时。缺少教师或出现同一教师时间冲突时，生成前校验会阻止排课并给出需要修正的记录。',
      target: tabPanelTarget('.sk-tabs', '任教关系', '.sk-assign .ant-table-wrapper', '.sk-assign'),
      beforeEnter: switchTab('.sk-tabs', '任教关系'),
    },
    {
      title: '建立可执行的排课规则',
      content: '规则组按年级或全校生效，可组合禁排时段、连堂、课程分散和教师负载等细则。若导览停在页签按钮，表示课位结构尚未保存；保存后即可进入并启用正确的规则组。',
      target: tabPanelTarget('.sk-tabs', '建立规则', '.rule-group-page', '.st-rules'),
      beforeEnter: switchTab('.sk-tabs', '建立规则'),
    },
    {
      title: '生成前确认范围与版本',
      content: '进入课表页后先确认学年、学期、年级和班级范围。“生成课表”会先校验数据与规则，再启动后台求解；已有课表会保留历史版本。若仍聚焦页签按钮，请先保存课位结构。',
      target: tabPanelTarget('.sk-tabs', '课表', '.sk-calendar-actions', '.sk-schedule-workspace'),
      beforeEnter: switchTab('.sk-tabs', '课表'),
    },
    {
      title: '查看结果、进度和冲突原因',
      content: '生成期间页面顶部持续显示阶段、耗时和求解进度；完成后可切换班级查看日课表，并用反向校验检查规则。若失败，诊断会指出冲突对象和建议调整项。',
      target: tabPanelTarget('.sk-tabs', '课表', '.sk-schedule-surface', '.sk-track', '.sk-schedule-workspace'),
      beforeEnter: switchTab('.sk-tabs', '课表'),
    },
  ],
  '/settings': [
    { title: '学年与届次', content: '基础配置核对当前学年、学期和高考模式；届次管理维护各入学届别。', target: '.ant-tabs-nav-list' },
    { title: '年级基础数据', content: '先建校区，再在这里建高一/高二/高三；年级部只关联这里的年级。', target: '.stg-grade-panel__header' },
  ],
  '/students': [
    { title: '学生统计', content: '在校、未分班等关键数字，先看总量再处理名单。', target: '.zh-stat-strip' },
    { title: '筛选与导入', content: '按年级、班级、状态筛选学生；名单导入入口也在本页。', target: '.zh-filter-row' },
    { title: '学生名单', content: '这里维护学生档案和班级归属。批量操作前先核对当前筛选范围。', target: '.ant-table-wrapper' },
  ],
  '/classes': [
    { title: '班级页签', content: '行政班与配套规则组在这里切换维护。', target: '.zh-class-tabs' },
    { title: '班级列表', content: '先选年级再建班；班主任、教室都可以在这里指定。', target: '.zh-class-list' },
  ],
  '/file-center': [
    { title: '任务筛选', content: '按导入、导出和业务类型查找文件任务；点击刷新获取后台最新状态。', target: '.zh-table-card-head' },
    { title: '任务列表', content: '进度、成功与失败数量都在这里。任务完成且文件可用后，下载按钮才会启用。', target: '.ant-table-wrapper' },
  ],
  '/staff': [
    { title: '组织范围', content: '先在左侧选择学校、部门或未分配人员，右侧名单会跟随当前组织范围。', target: '.personnel-tree-panel' },
    { title: '人员筛选', content: '在当前组织范围内按姓名、手机号和状态筛选，便于定位具体人员。', target: '.personnel-filters' },
    { title: '人员目录', content: '这里维护人员账号与组织归属；停用账号前先确认其承担的岗位和教务任务。', target: '.personnel-directory' },
  ],
  '/staff-positions': [
    { title: '人员筛选', content: '按姓名、岗位和账号状态查找人员，筛选结果决定下方当前操作范围。', target: '.zh-filter-row' },
    { title: '岗位配置', content: '在这里为人员分配岗位和教务职责。岗位会影响菜单与业务权限，请保存后再核对账号能力。', target: '.ant-table-wrapper' },
  ],
  '/rbac': [
    { title: '角色列表', content: '左侧选择要维护的角色；系统内置角色可查看，学校自定义角色可按权限边界维护。', target: '.zh-rbac-roles' },
    { title: '角色信息', content: '先确认角色名称、状态和适用对象，再配置菜单与操作权限。', target: '.zh-rbac-role-meta' },
    { title: '权限范围', content: '勾选决定该角色能看到和执行的功能。保存前检查敏感写操作是否确有需要。', target: firstOf('.zh-rbac-menu-tree', '.zh-rbac-workbench') },
  ],
  '/campus-buildings': [
    {
      title: '先看空间资源流程',
      content: '本页按“空间资源配置 → 资源分配规则 → 班级划分”推进：先建真实空间，再把教室分给届别，最后按教室生成或绑定行政班。导览会自动切换三个页签。',
      target: firstOf('.facility-tabs .ant-tabs-nav-list', '.facility-tabs [role="tablist"]'),
    },
    {
      title: '按校区、楼宇、场室逐级创建',
      content: '先新增校区，再选择校区新增楼宇，最后选择楼宇新增场室。场室的容量、类型以及是否允许排课、排考和会议，会被后续业务直接使用。',
      target: tabPanelTarget('.facility-tabs', '空间资源配置', '.facility-actions'),
      beforeEnter: switchTab('.facility-tabs', '空间资源配置'),
    },
    {
      title: '从左侧选择当前空间节点',
      content: '“学校空间”是根节点，下面依次展开校区、楼宇和楼层。点击你要维护的节点，例如“本部校区”，右侧内容和新增操作都会切换到这个范围。节点后的数字表示其当前下级资源数量。',
      target: tabPanelTarget('.facility-tabs', '空间资源配置', '.facility-tree-panel .ant-tree-node-content-wrapper-selected', '.facility-tree-panel'),
      beforeEnter: switchTab('.facility-tabs', '空间资源配置'),
    },
    {
      title: '在右侧核对下级资源',
      content: '这里列出当前节点直属的校区、楼宇、楼层或场室。继续点入某一行对应的树节点，可以逐层查看；场室要重点核对容量、资源标签和使用状态。',
      target: tabPanelTarget('.facility-tabs', '空间资源配置', '.facility-directory'),
      beforeEnter: switchTab('.facility-tabs', '空间资源配置'),
    },
    {
      title: '把空间按规则分配给届别',
      content: '分配规则可限定学年学期、目标届别、校区、楼宇、楼层、场室类型及共享方式。先预览匹配教室，确认范围正确后再执行，避免把专属资源分给错误届别。',
      target: tabPanelTarget('.facility-tabs', '资源分配规则', '.facility-allocation-intro', '.facility-allocation-resource-list'),
      beforeEnter: switchTab('.facility-tabs', '资源分配规则'),
    },
    {
      title: '核对规则状态和匹配数量',
      content: '每行是一条分配规则。重点检查目标届别、资源范围、共享或专属方式、匹配教室数及生效状态；需要追溯时可打开“查看资源”。',
      target: tabPanelTarget('.facility-tabs', '资源分配规则', '.facility-allocation-resource-list .ant-table-wrapper', '.facility-allocation-resource-list'),
      beforeEnter: switchTab('.facility-tabs', '资源分配规则'),
    },
    {
      title: '从已分配教室规划行政班',
      content: '这里只有已通过分配规则归属到届别的普通教室。可以按名称、楼宇和楼层筛选，再选择单间教室生成班级，或使用“按需生成班级”批量处理。',
      target: tabPanelTarget('.facility-tabs', '班级划分', '.facility-resource-toolbar', '.facility-allocation-resource-list'),
      beforeEnter: switchTab('.facility-tabs', '班级划分'),
    },
    {
      title: '确认教室与行政班的绑定结果',
      content: '每张卡显示教室位置、容量、所属届别和已绑定班级。生成或调整后，再进入班级管理补充班主任和学生名单；排课会使用这里确定的班级教室。',
      target: tabPanelTarget('.facility-tabs', '班级划分', '.facility-class-resource-grid', '.facility-allocation-resource-list'),
      beforeEnter: switchTab('.facility-tabs', '班级划分'),
    },
  ],
  '/teacher-profiles': [
    { title: '教师概览', content: '这里汇总教师、班主任、目标周课和已排课时，先判断整体任教数据是否完整。', target: '.tp-header' },
    { title: '教师筛选', content: '按学年学期、学科和班主任身份定位教师；下方完成度都基于当前筛选范围。', target: '.tp-filters' },
    { title: '任教完成度', content: '每位教师的班级、学科、目标课时和已排课时在这里对照；不足时先回到任教关系核对。', target: '.ant-table-wrapper' },
  ],
  '/ai-providers': [
    { title: '服务商说明', content: '给学校助手配置大模型；密钥只写不读，测试连通后再设为默认。', target: '.zh-page-desc' },
    { title: '服务商列表', content: '启用一条带对话模型的服务商助手即可工作；模型需支持工具调用才能生成草稿。', target: '.ant-table' },
  ],
  '/subjects': [
    { title: '科目管理', content: '这里维护学校实际使用的科目。排课、考试和成绩都引用同一份科目数据。', target: '.subject-hero' },
    { title: '科目操作', content: '新增科目前先检查是否已有同名科目；停用前确认没有正在使用的排课和考试数据。', target: '.subject-actions' },
    { title: '科目列表', content: '列表显示科目类型与状态，活动课和普通学科在排课规则中的处理方式不同。', target: '.subject-surface' },
  ],
  '/gaokao': [
    { title: '范围与模式', content: '先选择年级并确认学校高考模式，后续选科统计和教学班生成都按这个范围处理。', target: '.gk-filters' },
    { title: '业务进度', content: '这里显示选科确认、教学班和排课所处阶段；未满足前置条件时生成按钮不会启用。', target: '.gk-workflow' },
    { title: '选科数据', content: '组合人数和学科需求用于判断开班规模，生成前先处理页面提示的缺项。', target: '.gk-grid' },
  ],
  '/seating': [
    { title: '排座范围', content: '先选择考试和班级，再切换排座规则或座位结果；不同范围的座位方案相互独立。', target: '.st-tabs' },
    { title: '排座规则', content: '在这里设置座位顺序、需要分开的学生等条件，确认后再生成座位表。', target: '.st-rules' },
    { title: '座位结果', content: '生成后逐行核对考生与座位号；调整规则后需要重新生成并再次检查。', target: firstOf('.st-seat-grid', '.ant-table-wrapper') },
  ],
  '/exam-rooms': [
    { title: '排考流程', content: '顶部导航展示考场资源、使用范围、考试日程、监考教师和人员排考的先后关系。', target: '.es-nav' },
    { title: '考场资源', content: '这里选择可作为考场的场室，并核对容量。考场不足会影响后续考生安排。', target: '.es-room-manager' },
  ],
  '/exam-venues': [
    { title: '排考流程', content: '顶部导航可以在排考五个环节之间切换，建议按从左到右的顺序配置。', target: '.es-nav' },
    { title: '考试与考场范围', content: '先选择考试，再勾选本次实际使用的考场；保存后考试日程才有明确容量范围。', target: '.es-venue-picker' },
  ],
  '/exam-calendar': [
    { title: '排考流程', content: '当前处于考试日程环节，前一步应已准备好本次使用的考场。', target: '.es-nav' },
    { title: '日程配置', content: '设置考试日期、每天场次和科目时长；时间重叠会直接影响考场与监考安排。', target: '.es-config' },
    { title: '日程预览', content: '这里按日期查看考试场次。保存前核对科目、开始时间和结束时间。', target: '.es-surface' },
  ],
  '/exam-invigilators': [
    { title: '排考流程', content: '当前维护监考教师范围；完成后再进入人员排考。', target: '.es-nav' },
    { title: '选择考试', content: '教师可用性按考试保存，先确认当前考试，避免配置到错误批次。', target: '.es-exam-select' },
    { title: '教师状态', content: '按可用、请假或排除状态核对教师；状态会参与后续监考分配。', target: '.es-personnel' },
  ],
  '/exam-scheduling': [
    { title: '排考流程', content: '这是最后的人员排考环节，前面的考场、日程和教师可用性需要先准备完成。', target: '.es-nav' },
    { title: '选择考试', content: '先确认本次要处理的考试，页面指标和人员安排都会切换到该考试。', target: '.es-exam-select' },
    { title: '排考结果', content: '这里查看考生考场和监考教师安排。生成后仍需检查缺员、容量和时间冲突。', target: '.es-personnel' },
  ],
  '/meetings': [
    { title: '会议说明', content: '这里维护学校会议和场室占用，会议时间会与其他资源使用共同核对。', target: firstOf('.chapter', '.facility-notice') },
    { title: '会议列表', content: '按时间查看会议、地点和参与范围；新增前先确认场室在该时段可用。', target: '.ant-table-wrapper' },
  ],
  '/grading': [
    { title: '阅卷进度', content: '顶栏显示当前试卷、题号和已阅进度，切题前先确保当前评分已经保存。', target: '.zh-gbar' },
    { title: '答卷区域', content: '这里查看学生答卷或扫描图像，可缩放并定位需要评分的内容。', target: '.zh-sheet' },
    { title: '评分区域', content: '按评分标准录入分数和批注，提交后再进入下一份答卷。', target: firstOf('.zh-gside', '.zh-grading aside') },
  ],
  '/stats': [
    { title: '成绩概览', content: '这里汇总参考人数、平均分、最高分和最低分，先确认本次统计数据是否齐全。', target: '.st-sum-cards' },
    { title: '成绩分布', content: '图表展示分数段、班级和题目维度的表现，用于定位需要复盘的班级或知识点。', target: '.st-charts' },
  ],
}

export function tourForPathname(pathname: string): TourStep[] | null {
  if (PAGE_TOURS[pathname]) return PAGE_TOURS[pathname]
  const hit = Object.keys(PAGE_TOURS).find((p) => pathname.startsWith(`${p}/`))
  return hit ? PAGE_TOURS[hit] : null
}

export function resolveTarget(target: TourTarget): Element | null {
  try {
    return typeof target === 'function' ? target() : document.querySelector(target)
  } catch {
    return null
  }
}
