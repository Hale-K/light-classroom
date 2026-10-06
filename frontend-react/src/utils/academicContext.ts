/**
 * 学年学期是跨页面共享的租户配置。保存成功后广播这个事件，
 * 让布局和当前页面重新读取后端的权威值。
 */
export const ACADEMIC_CONTEXT_CHANGED = 'academic-context-changed'
