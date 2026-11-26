import {
  AuditOutlined,
  BankOutlined,
  DownOutlined,
  HomeOutlined,
  InboxOutlined,
  KeyOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  ShopOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { App, Badge, Button, Dropdown, Flex, Layout, Menu, type MenuProps, Select, Spin, theme, Tooltip, Typography } from 'antd';
import { type ReactNode, Suspense, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { errorMessage } from '@/lib/api';
import { useApprovalInbox } from '@/lib/approvals';
import { hasPermission } from '@/lib/permissions';

import { useAuth, useMe } from './AuthProvider';
import { PermissionOutlet } from './guards';
import { buildMenu, findActiveEntry } from './menu';
import { PATHS } from './paths';
import { type MenuEntry, menuEntries, type MenuGroupKey } from './registry';

const COLLAPSED_KEY = 'erp.sider-collapsed';
const HOME_KEY = 'home';

const GROUP_ICONS: Record<MenuGroupKey, ReactNode> = {
  finans: <BankOutlined />,
  malzeme: <InboxOutlined />,
  yonetim: <SettingOutlined />,
};

type MenuItems = NonNullable<MenuProps['items']>;

function groupKey(group: MenuGroupKey): string {
  return `group:${group}`;
}

function sectionKey(group: MenuGroupKey, section: string): string {
  return `section:${group}:${section}`;
}

function entryItem(entry: MenuEntry): MenuItems[number] {
  return { key: entry.key, label: <Link to={entry.path}>{entry.label}</Link> };
}

/** Keys of the submenus that contain an entry. */
function ancestorKeys(entry: MenuEntry | undefined): string[] {
  if (!entry) {
    return [];
  }
  return entry.section ? [groupKey(entry.group), sectionKey(entry.group, entry.section)] : [groupKey(entry.group)];
}

/** Frame of every authenticated page: navigation, company switcher, approvals, user menu. */
export function AppLayout(): ReactNode {
  const me = useMe();
  const { logout, switchCompany } = useAuth();
  const { token } = theme.useToken();
  const { message } = App.useApp();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const inbox = useApprovalInbox();

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSED_KEY) === '1');
  const [switching, setSwitching] = useState(false);

  const groups = useMemo(() => buildMenu(menuEntries, (permission) => hasPermission(me, permission)), [me]);
  const activeEntry = useMemo(() => findActiveEntry(menuEntries, pathname), [pathname]);
  const [openKeys, setOpenKeys] = useState(() => ancestorKeys(activeEntry));

  // Navigating by link or URL must reveal the entry of the new page.
  useEffect(() => {
    setOpenKeys((keys) => [...new Set([...keys, ...ancestorKeys(activeEntry)])]);
  }, [activeEntry]);

  const toggleCollapsed = (next: boolean): void => {
    setCollapsed(next);
    localStorage.setItem(COLLAPSED_KEY, next ? '1' : '0');
  };

  const menuItems: MenuItems = [
    { key: HOME_KEY, icon: <HomeOutlined />, label: <Link to={PATHS.home}>Ana Sayfa</Link> },
    ...groups.map((group) => ({
      key: groupKey(group.key),
      icon: GROUP_ICONS[group.key],
      label: group.label,
      children: [
        ...group.entries.map(entryItem),
        ...group.sections.map((section) => ({
          key: sectionKey(group.key, section.title),
          label: section.title,
          children: section.entries.map(entryItem),
        })),
      ],
    })),
  ];
  const selectedKeys = activeEntry ? [activeEntry.key] : pathname === PATHS.home ? [HOME_KEY] : [];

  const company = me.companies.find((candidate) => candidate.id === me.company_id);
  const handleCompanyChange = async (companyId: number): Promise<void> => {
    setSwitching(true);
    try {
      // Pages of the previous company (an open document, say) mean nothing in the new one.
      navigate(PATHS.home);
      await switchCompany(companyId);
    } catch (error) {
      void message.error(errorMessage(error));
    } finally {
      setSwitching(false);
    }
  };

  const userMenu: MenuProps = {
    items: [
      { key: 'password', icon: <KeyOutlined />, label: 'Şifre değiştir' },
      { type: 'divider' },
      { key: 'logout', icon: <LogoutOutlined />, label: 'Çıkış yap' },
    ],
    onClick: ({ key }) => {
      if (key === 'password') {
        navigate(PATHS.changePassword);
      } else {
        logout();
      }
    },
  };

  const pendingApprovals = inbox.data?.length ?? 0;

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider
        theme="dark"
        width={240}
        collapsedWidth={52}
        collapsible
        collapsed={collapsed}
        trigger={null}
        breakpoint="lg"
        onBreakpoint={(narrow) => narrow && toggleCollapsed(true)}
        style={{ position: 'sticky', top: 0, height: '100vh', overflowY: 'auto' }}
      >
        <Flex
          align="center"
          justify={collapsed ? 'center' : 'flex-start'}
          style={{ height: 46, paddingInline: collapsed ? 0 : 20, color: '#ffffff', fontWeight: 600, letterSpacing: 1 }}
        >
          {collapsed ? 'E' : 'ERP'}
        </Flex>
        <Menu
          theme="dark"
          mode="inline"
          inlineIndent={16}
          items={menuItems}
          selectedKeys={selectedKeys}
          // While collapsed the submenus are popups that the menu opens and closes by itself.
          {...(collapsed ? {} : { openKeys, onOpenChange: setOpenKeys })}
          style={{ borderInlineEnd: 0 }}
        />
      </Layout.Sider>

      <Layout>
        <Layout.Header
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            aria-label={collapsed ? 'Menüyü genişlet' : 'Menüyü daralt'}
            onClick={() => toggleCollapsed(!collapsed)}
          />
          <Flex align="center" gap={4}>
            {me.companies.length > 1 ? (
              <Select<number>
                variant="borderless"
                prefix={<ShopOutlined />}
                aria-label="Şirket"
                value={me.company_id}
                loading={switching}
                disabled={switching}
                popupMatchSelectWidth={false}
                options={me.companies.map((item) => ({ value: item.id, label: `${item.code} · ${item.name}` }))}
                onChange={(companyId) => void handleCompanyChange(companyId)}
              />
            ) : (
              <Typography.Text style={{ paddingInline: 8 }}>
                <ShopOutlined /> {company ? `${company.code} · ${company.name}` : ''}
              </Typography.Text>
            )}
            <Tooltip title="Onay bekleyen belgeler">
              <Badge count={pendingApprovals} size="small" offset={[-6, 6]}>
                <Button
                  type="text"
                  icon={<AuditOutlined />}
                  aria-label={`Onay bekleyen belgeler: ${pendingApprovals}`}
                  onClick={() => navigate(PATHS.approvals)}
                />
              </Badge>
            </Tooltip>
            <Dropdown menu={userMenu} trigger={['click']}>
              <Button type="text" icon={<UserOutlined />}>
                {me.full_name}
                <DownOutlined style={{ fontSize: 10 }} />
              </Button>
            </Dropdown>
          </Flex>
        </Layout.Header>

        <Layout.Content style={{ padding: 16, minWidth: 0 }}>
          <Suspense fallback={<Spin style={{ display: 'block', marginTop: 96 }} />}>
            <PermissionOutlet />
          </Suspense>
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
