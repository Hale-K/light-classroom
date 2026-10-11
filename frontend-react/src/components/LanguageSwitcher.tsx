import { getLocale, setLocale, translate as t, useLocale, type AppLocale } from '@/i18n'
import './language-switcher.css'

export default function LanguageSwitcher() {
  useLocale()
  return (
    <label className="language-switcher">
      <span aria-hidden="true">◎</span>
      <select aria-label={t('界面语言')} value={getLocale()} onChange={event => void setLocale(event.target.value as AppLocale)}>
        <option value="zh-CN" lang="zh-CN">简体中文</option>
        <option value="zh-TW" lang="zh-TW">繁體中文</option>
        <option value="en-US" lang="en-US">English</option>
      </select>
    </label>
  )
}
