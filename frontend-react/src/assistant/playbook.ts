/** 高频问法本地作答，与后端 PLAYBOOK 对齐；其余进大模型。 */

export function isHowToUse(text: string): boolean {
  if (/系统怎么用|如何使用系统|怎样使用系统|第一次(用|登录)|教务怎么用/.test(text)) return true
  if (/排课(的)?(步骤|流程)|怎么排课|如何排课|怎样排课/.test(text)) return true
  return /告诉我.{0,12}排课/.test(text) && /步骤|流程|怎么|如何/.test(text)
}

export function isSchedulingPageHelp(text: string): boolean {
  return /排课.*(怎么用|如何用|怎么使用|怎么操作|怎么弄)|这个页(面)?.{0,8}(怎么用|如何用|怎么使用)/.test(text)
}

const PAIRS: { test: RegExp; answer: string }[] = [
  {
    test: /生成.{0,6}(多久|多长时间|要等)|排课.{0,4}超时|生成课表要等多久/,
    answer:
      '生成走后台任务。耗时取决于课量和规则，请查看生成面板的实际进展。冲突格会标红。',
  },
  {
    test: /排课.{0,8}调课|调课.{0,8}排课|手工调课/,
    answer:
      '排课按规则生成整张课表；调课只改已有格子，不会重跑求解器。目标格被占用会提示碰撞，换空格或先把原课挪开。我不会改格子。',
  },
  {
    test: /完成度|课时算满|档案.{0,6}对不上/,
    answer:
      '教师档案完成度按网格可排课时核算，单双周按 0.5 计，上限 100%。停用教师不进列表。去教师档案页可以看本校数字。',
  },
  {
    test: /晚自习|晚课|晚上第/,
    answer:
      '课位结构里每天晚课只有 1 节。课时管理里晚课填 0、0.5 或 1：1 为单双周同一科目不拆；0.5 要选单周或双周并与另一门 0.5 对课。各班晚课应排满一周，晚自习不排自主学习。口头「第 8、9 节」必须先对上网格。',
  },
  {
    test: /改了学年|课表空了|网格.{0,6}空/,
    answer: '学年学期和网格决定容量。改完旧课表不会自动迁移，需要重新生成。我不会替你保存设置或滚动学年。',
  },
  {
    test: /数据会串|别的学校|多所学校|多租户/,
    answer: '不会串。登录后只看见本校数据。',
  },
  {
    test: /导入学生|学生名单/,
    answer: '在「学生档案」里导入。排课前还要有年级和行政班。',
  },
  {
    test: /导出课表|课表文件/,
    answer: '在排课页或「文件中心」导出。任务在后台跑，完成后去文件中心取。',
  },
  {
    test: /任教.{0,6}自动|按课时.{0,4}任教/,
    answer: '可以按课时方案自动生成任教关系：先校验通过再写入。生成课表若提示缺任教，先把任教补齐。',
  },
  {
    test: /排座|座位/,
    answer: '班级排座在「班级排座」，和排课生成的日课表不是同一件事。',
  },
]

export function matchPlaybook(text: string): string | null {
  const t = text.trim()
  if (!t) return null
  const hit = PAIRS.find((p) => p.test.test(t))
  return hit ? hit.answer : null
}
