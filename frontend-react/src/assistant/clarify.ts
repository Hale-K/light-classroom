/** 只落到教务对象。不枚举其它行业。 */

const LOW = /快用完|用完了|快没了|不够排|不够了|快满了|用尽/
const STUCK = /卡住|卡死|出不来|一直转|转圈|排不出来/
const TEACHER_HINT = /老师|教师|完成度|课时满|周课时/
const GRID_HINT = /格子|网格|课位|容量/
const GEN_HINT = /生成|红格|标红|求解/
const EVENING = /^晚上$|晚上怎么|晚上的课|晚上排/
const IN_DOMAIN =
  /课|排|班|年级|高[一二三]|老师|教师|档案|网格|格子|课位|规则|生成|学年|科目|晚自习|晚课|调课|任教|完成度|节|系统怎么用|教务|连堂|禁排|固定|空堂|导入|导出|学生|排座|名单|备课|对课/

export const Q_LOW = '你是说一周格子快排满，还是某科课时还没填够，还是某位老师周课时快满了？'
export const Q_STUCK = '是点了「生成课表」还在转，还是格子已经标红？'
export const Q_EVENING = '网格里晚自习是第几节？课时里晚课填 0、0.5 或 1，必须先对上课位结构。'
export const Q_SCOPE = '我只做本校排课：课时、课位、任教、规则、生成。请用这些话说。'

export function clarify(text: string): { ask: boolean; text: string; code: string } | null {
  const q = text.trim()
  if (!q || q.length > 200) return null

  if (LOW.test(q)) {
    if (TEACHER_HINT.test(q) && !GRID_HINT.test(q)) {
      return {
        ask: false,
        text: '按教师档案看：完成度接近 100% 表示按网格课时已排满；某位老师周课时是否超上限要到档案或任教里点开看。说姓名或科目我才能查本校人数。',
        code: 'teacher_load',
      }
    }
    if (GRID_HINT.test(q) && !TEACHER_HINT.test(q)) {
      return {
        ask: false,
        text: '一周能排几节由课位结构决定。总额超过天数×节次就排不下。去排课「课位结构」核对，我不会改网格。',
        code: 'grid_cap',
      }
    }
    return { ask: true, text: Q_LOW, code: 'low_ambiguous' }
  }

  if (STUCK.test(q) && !/导入|登录|验证码/.test(q)) {
    if (GEN_HINT.test(q) && /红|标红/.test(q)) {
      return {
        ask: false,
        text: '红格是冲突或规则不满足。看诊断：课时超额、缺任教、规则互斥。',
        code: 'red_cell',
      }
    }
    return { ask: true, text: Q_STUCK, code: 'stuck_ambiguous' }
  }

  if (EVENING.test(q) && !/0\.5|晚自习|课位/.test(q)) {
    return { ask: true, text: Q_EVENING, code: 'evening_ambiguous' }
  }

  if (!IN_DOMAIN.test(q) && !/怎么用|第一次/.test(q)) {
    return { ask: true, text: Q_SCOPE, code: 'out_of_scope' }
  }

  return null
}
