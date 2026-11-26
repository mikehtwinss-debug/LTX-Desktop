import { CheckOutlined, CloseOutlined } from '@ant-design/icons';
import { Alert, App, Button, Card, Empty, Flex, Input, Skeleton, Steps, type StepsProps, Typography } from 'antd';
import { type ReactNode, useState } from 'react';

import { errorMessage } from '@/lib/api';
import {
  type ApprovalDecision,
  type ApprovalRequest,
  type ApprovalStatus,
  type ApprovalStep,
  type ApprovalStepStatus,
  useApprovalAction,
  useApprovalHistory,
} from '@/lib/approvals';
import { fmtDateTime, fmtMoney } from '@/lib/format';

import { type StatusMap, StatusTag } from './StatusTag';

export const APPROVAL_STATUS: StatusMap<ApprovalStatus> = {
  PENDING: { label: 'Onay bekliyor', color: 'gold' },
  APPROVED: { label: 'Onaylandı', color: 'green' },
  REJECTED: { label: 'Reddedildi', color: 'red' },
  CANCELLED: { label: 'İptal edildi', color: 'default' },
};

const STEP_STATUS: Record<ApprovalStepStatus, { label: string; progress: NonNullable<StepsProps['status']> }> = {
  WAITING: { label: 'Sırada', progress: 'wait' },
  PENDING: { label: 'Karar bekleniyor', progress: 'process' },
  APPROVED: { label: 'Onayladı', progress: 'finish' },
  REJECTED: { label: 'Reddetti', progress: 'error' },
  SKIPPED: { label: 'Atlandı', progress: 'wait' },
};

const COMMENT_MAX_LENGTH = 500;

function stepDescription(step: ApprovalStep): ReactNode {
  const { label } = STEP_STATUS[step.status];
  return (
    <>
      <div>
        {step.acted_by ? `${label}: ${step.acted_by.full_name} · ${fmtDateTime(step.acted_at)}` : label}
      </div>
      {step.comment && <Typography.Text type="secondary">“{step.comment}”</Typography.Text>}
    </>
  );
}

interface RequestCardProps {
  request: ApprovalRequest;
  onDecided?: (request: ApprovalRequest) => void;
}

function RequestCard({ request, onDecided }: RequestCardProps): ReactNode {
  const { message } = App.useApp();
  const action = useApprovalAction();
  const [comment, setComment] = useState('');
  const [commentMissing, setCommentMissing] = useState(false);
  const canDecide = request.status === 'PENDING' && request.can_act;

  const decide = (decision: ApprovalDecision): void => {
    const text = comment.trim();
    if (decision === 'reject' && text === '') {
      setCommentMissing(true);
      return;
    }
    action.mutate(
      { requestId: request.id, decision, comment: text || null },
      {
        onSuccess: (updated) => {
          void message.success(decision === 'approve' ? 'Belge onaylandı' : 'Belge reddedildi');
          setComment('');
          onDecided?.(updated);
        },
      },
    );
  };

  return (
    <Card size="small">
      <Flex align="center" gap={8} wrap style={{ marginBottom: 12 }}>
        <StatusTag map={APPROVAL_STATUS} value={request.status} />
        <Typography.Text strong>{fmtMoney(request.amount, request.document?.currency)}</Typography.Text>
        <Typography.Text type="secondary">
          {request.requested_by.full_name} tarafından {fmtDateTime(request.requested_at)} tarihinde onaya gönderildi
        </Typography.Text>
      </Flex>

      <Steps
        direction="vertical"
        size="small"
        items={request.steps.map((step) => ({
          title: `${step.level}. seviye · ${step.approver_user?.full_name ?? step.approver_role?.name ?? 'Onaylayıcı'}`,
          description: stepDescription(step),
          status: STEP_STATUS[step.status].progress,
        }))}
      />

      {canDecide && (
        <Flex vertical gap={8}>
          <Input.TextArea
            rows={2}
            maxLength={COMMENT_MAX_LENGTH}
            placeholder="Açıklama (reddederken zorunlu)"
            aria-label="Onay açıklaması"
            status={commentMissing ? 'error' : undefined}
            value={comment}
            onChange={(event) => {
              setComment(event.target.value);
              setCommentMissing(false);
            }}
          />
          {commentMissing && <Typography.Text type="danger">Reddetmek için bir açıklama yazın.</Typography.Text>}
          <Flex gap={8}>
            <Button
              type="primary"
              icon={<CheckOutlined />}
              loading={action.isPending && action.variables.decision === 'approve'}
              disabled={action.isPending}
              onClick={() => decide('approve')}
            >
              Onayla
            </Button>
            <Button
              danger
              icon={<CloseOutlined />}
              loading={action.isPending && action.variables.decision === 'reject'}
              disabled={action.isPending}
              onClick={() => decide('reject')}
            >
              Reddet
            </Button>
          </Flex>
        </Flex>
      )}
    </Card>
  );
}

export interface ApprovalPanelProps {
  /** Approval object type of the document: `PR`, `QCMP`, `PO`, ... */
  objectType: string;
  objectId: number;
  /** Called after the user approved or rejected, e.g. to reload the document and its status. */
  onDecided?: (request: ApprovalRequest) => void;
}

/**
 * Approval history of a document, newest request first, with the approve/reject form when the
 * signed-in user may decide the current step.
 *
 *   <ApprovalPanel objectType="PO" objectId={order.id} onDecided={() => orderQuery.refetch()} />
 */
export function ApprovalPanel({ objectType, objectId, onDecided }: ApprovalPanelProps): ReactNode {
  const history = useApprovalHistory(objectType, objectId);

  if (history.isPending) {
    return <Skeleton active paragraph={{ rows: 3 }} />;
  }
  if (history.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={errorMessage(history.error)}
        action={
          <Button size="small" onClick={() => void history.refetch()}>
            Tekrar dene
          </Button>
        }
      />
    );
  }
  if (history.data.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Bu belge için onay süreci başlatılmamış" />;
  }

  const newestFirst = [...history.data].sort((a, b) => b.id - a.id);
  return (
    <Flex vertical gap={8}>
      {newestFirst.map((request) => (
        <RequestCard key={request.id} request={request} onDecided={onDecided} />
      ))}
    </Flex>
  );
}
