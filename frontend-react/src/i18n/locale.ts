export const LOCALE_STORAGE_KEY = 'light_classroom_locale'
export const SUPPORTED_LOCALES = ['zh-CN', 'zh-TW', 'en-US'] as const
export type AppLocale = typeof SUPPORTED_LOCALES[number]

export function resolveLocale(value?: string | null): AppLocale | undefined {
  if (!value) return undefined
  const normalized = value.replaceAll('_', '-').toLowerCase()
  if (/^zh-(tw|hk|mo|hant)(-|$)/.test(normalized)) return 'zh-TW'
  if (/^zh(-|$)/.test(normalized)) return 'zh-CN'
  if (/^en(-|$)/.test(normalized)) return 'en-US'
  return undefined
}

export function readLocale(storage: Pick<Storage, 'getItem'> | null, languages: readonly string[]): AppLocale {
  try {
    const saved = resolveLocale(storage?.getItem(LOCALE_STORAGE_KEY))
    if (saved) return saved
  } catch { /* Storage may be disabled in embedded browsers. */ }
  for (const language of languages) {
    const locale = resolveLocale(language)
    if (locale) return locale
  }
  return 'zh-CN'
}

export function persistLocale(storage: Pick<Storage, 'setItem'> | null, locale: AppLocale): void {
  try { storage?.setItem(LOCALE_STORAGE_KEY, locale) } catch { /* In-memory switching remains available. */ }
}
