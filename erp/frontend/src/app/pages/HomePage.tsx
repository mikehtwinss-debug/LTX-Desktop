import { AuditOutlined } from '@ant-design/icons';
import { Card, Col, Empty, Flex, Row, Statistic, Typography } from 'antd';
import { type ReactNode, useMemo } from 'react';
import { Link } from 'react-router-dom';

import { PageHeader } from '@/components/PageHeader';
import { useApprovalInbox } from '@/lib/approvals';
import { hasPermission } from '@/lib/permissions';

import { useMe } from '../AuthProvider';
import { buildMenu } from '../menu';
import { PATHS } from '../paths';
import { type MenuEntry, menuEntries } from '../registry';

function QuickLinks({ title, entries }: { title?: string; entries: MenuEntry[] }): ReactNode {
  if (entries.length === 0) {
    return null;
  }
  return (
    <div>
      {title !== undefined && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 4 }}>
          {title}
        </Typography.Text>
      )}
      <Flex gap="4px 16px" wrap>
        {entries.map((entry) => (
          <Link key={entry.key} to={entry.path}>
            {entry.label}
          </Link>
        ))}
      </Flex>
    </div>
  );
}

export function HomePage(): ReactNode {
  const me = useMe();
  const inbox = useApprovalInbox();
  const groups = useMemo(() => buildMenu(menuEntries, (permission) => hasPermission(me, permission)), [me]);
  const company = me.companies.find((candidate) => candidate.id === me.company_id);

  return (
    <>
      <PageHeader title={`Hoş geldiniz, ${me.full_name}`} subtitle={company && `${company.code} · ${company.name}`} />
      <Row gutter={[12, 12]}>
        <Col xs={24} md={8} xl={6}>
          <Card size="small">
            <Statistic
              title="Onayınızı bekleyen belgeler"
              prefix={<AuditOutlined />}
              loading={inbox.isPending}
              value={inbox.data?.length ?? '—'}
            />
            <Link to={PATHS.approvals}>Onay kutusuna git</Link>
          </Card>
        </Col>
        {groups.map((group) => (
          <Col key={group.key} xs={24} md={16} xl={18}>
            <Card size="small" title={group.label}>
              <Flex vertical gap={12}>
                <QuickLinks entries={group.entries} />
                {group.sections.map((section) => (
                  <QuickLinks key={section.title} title={section.title} entries={section.entries} />
                ))}
              </Flex>
            </Card>
          </Col>
        ))}
        {groups.length === 0 && (
          <Col xs={24} md={16} xl={18}>
            <Card size="small">
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="Hesabınıza tanımlı bir işlem bulunmuyor. Yetki için sistem yöneticinize başvurun."
              />
            </Card>
          </Col>
        )}
      </Row>
    </>
  );
}
