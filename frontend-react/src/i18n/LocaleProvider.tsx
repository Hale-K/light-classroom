import type { ReactNode } from 'react'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import zhTW from 'antd/locale/zh_TW'
import enUS from 'antd/locale/en_US'
import { useLocale } from './index'

const locales = { 'zh-CN': zhCN, 'zh-TW': zhTW, 'en-US': enUS }

export default function LocaleProvider({ children }: { children: ReactNode }) {
  const locale = useLocale()
  return <ConfigProvider locale={locales[locale]}>{children}</ConfigProvider>
}
