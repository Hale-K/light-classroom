import { Tabs } from 'antd'
import { useSearchParams } from 'react-router-dom'
import CampusBuildingsView from '@/pages/campus-buildings'
import Icon from '@/components/Icon'

export default function SpaceResourcesView() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = searchParams.get('tab') || 'resources'

  return <div className="zh-page facility-page">
    <Tabs
      className="facility-tabs"
      activeKey={activeTab}
      onChange={(key) => {
        const next = new URLSearchParams(searchParams)
        next.set('tab', key)
        setSearchParams(next, { replace: true })
      }}
      items={[
        {
          key: 'resources',
          label: <span className="facility-tab-label"><Icon name="building" size={16} />空间资源配置</span>,
          children: activeTab === 'resources' ? <CampusBuildingsView embedded focus="resources" /> : null,
        },
        {
          key: 'allocation',
          label: <span className="facility-tab-label"><Icon name="sitemap" size={16} />资源分配规则</span>,
          children: activeTab === 'allocation' ? <CampusBuildingsView embedded focus="allocation" /> : null,
        },
        {
          key: 'class-planning',
          label: <span className="facility-tab-label"><Icon name="id-badge" size={16} />班级划分</span>,
          children: activeTab === 'class-planning' ? <CampusBuildingsView embedded focus="class-planning" /> : null,
        },
      ]}
    />
  </div>
}
