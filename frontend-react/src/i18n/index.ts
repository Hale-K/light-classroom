import i18n from 'i18next'
import { initReactI18next, useTranslation } from 'react-i18next'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import 'dayjs/locale/zh-tw'
import zhCN from './locales/zh-CN.json'
import zhTW from './locales/zh-TW.json'
import enUS from './locales/en-US.json'
import { readLocale, resolveLocale, persistLocale, type AppLocale, LOCALE_STORAGE_KEY } from './locale'

export { SUPPORTED_LOCALES, type AppLocale } from './locale'

function storage(): Storage | null {
  try { return window.localStorage } catch { return null }
}

const initialLocale = readLocale(storage(), navigator.languages || [navigator.language])
void i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    'zh-TW': { translation: zhTW },
    'en-US': { translation: enUS },
  },
  lng: initialLocale,
  supportedLngs: ['zh-CN', 'zh-TW', 'en-US'],
  fallbackLng: 'zh-CN',
  keySeparator: false,
  nsSeparator: false,
  initAsync: false,
  interpolation: { escapeValue: false }, // React escapes rendered text.
  returnNull: false,
})

export function getLocale(): AppLocale {
  return resolveLocale(i18n.resolvedLanguage || i18n.language) || 'zh-CN'
}

function applyLocale() {
  const locale = getLocale()
  document.documentElement.lang = locale
  document.title = translate('轻课堂 · 教务')
  dayjs.locale(locale === 'en-US' ? 'en' : locale.toLowerCase())
}
i18n.on('languageChanged', applyLocale)
applyLocale()

export function setLocale(locale: AppLocale) {
  persistLocale(storage(), locale)
  return i18n.changeLanguage(locale)
}

window.addEventListener('storage', event => {
  if (event.key === LOCALE_STORAGE_KEY) {
    const locale = resolveLocale(event.newValue)
    if (locale) void i18n.changeLanguage(locale)
  }
})

/** Source-language keys keep existing Chinese copy reviewable. Unknown keys fall back unchanged. */
export function translate(source: string, values?: Record<string, unknown>): string {
  return i18n.t(source, { ...values, defaultValue: source })
}

/** Subscribe without remounting pages, preserving form values and unsaved edits. */
export function useLocale(): AppLocale {
  useTranslation()
  return getLocale()
}

export function formatDate(value: string | number | Date, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(getLocale(), options || { year: 'numeric', month: 'short', day: 'numeric' }).format(new Date(value))
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(getLocale(), options).format(value)
}

export default i18n
