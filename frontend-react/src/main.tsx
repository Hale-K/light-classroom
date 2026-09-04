import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntdApp, ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

// 正文近黑，辅文仍分层，避免整页发灰
const themeConfig = {
  token: {
    colorPrimary: '#111111',
    colorInfo: '#1F6C9F',
    colorLink: '#1F6C9F',
    colorSuccess: '#346538',
    colorWarning: '#956400',
    colorError: '#9F2F2D',
    colorBgBase: '#FBFBFA',
    colorBgContainer: '#FFFFFF',
    colorBgElevated: '#FFFFFF',
    colorBorder: '#EAEAEA',
    colorBorderSecondary: '#F0F0EF',
    colorTextBase: '#111111',
    colorText: '#111111',
    colorTextSecondary: '#3f3f46',
    colorTextTertiary: '#71717a',
    colorTextHeading: '#0a0a0a',
    borderRadius: 8,
    fontFamily:
      "'Geist','Helvetica Neue','Noto Sans SC','PingFang SC','Microsoft YaHei',sans-serif",
    fontSize: 14,
    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.03)',
    boxShadowSecondary: '0 2px 8px rgba(0, 0, 0, 0.04)',
    fontSizeHeading1: 26,
    fontSizeHeading2: 22,
    fontSizeHeading3: 18,
    fontSizeHeading4: 16,
    fontSizeHeading5: 14,
  },
  components: {
    Layout: {
      siderBg: '#F7F6F3',
      headerBg: 'rgba(251,251,250,0.85)',
      headerHeight: 60,
      bodyBg: 'transparent',
    },
    Menu: {
      itemBg: 'transparent',
      itemColor: '#171717',
      itemHoverBg: '#F0F0EF',
      itemHoverColor: '#0a0a0a',
      itemSelectedBg: '#E9E9E7',
      itemSelectedColor: '#0a0a0a',
      groupTitleColor: '#52525b',
      itemBorderRadius: 8,
      itemMarginInline: 8,
      itemHeight: 40,
    },
    Table: {
      headerBg: '#F7F6F3',
      headerColor: '#3f3f46',
      headerSplitColor: 'transparent',
      headerBorderRadius: 8,
      rowHoverBg: '#F7F6F3',
      borderColor: '#EAEAEA',
    },
    Card: {
      colorBgContainer: '#FFFFFF',
      colorBorderSecondary: '#EAEAEA',
      borderRadiusLG: 10,
    },
    Button: {
      controlHeight: 40,
      fontWeight: 500,
      borderRadius: 6,
      primaryColor: '#FFFFFF',
      primaryShadow: 'none',
    },
    Input: {
      colorBgContainer: '#FFFFFF',
      borderRadius: 6,
      activeShadow: '0 0 0 2px rgba(17, 17, 17, 0.06)',
    },
    Select: {
      colorBgContainer: '#FFFFFF',
      borderRadius: 6,
    },
    Modal: {
      contentBg: '#FFFFFF',
      headerBg: '#FFFFFF',
      titleFontSize: 16,
    },
    Switch: {
      colorPrimary: '#111111',
    },
    Tag: {
      borderRadiusSM: 8,
    },
  },
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider locale={zhCN} theme={themeConfig}>
        <AntdApp>
          <App />
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  </StrictMode>,
)
