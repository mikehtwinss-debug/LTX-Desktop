import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiGet, apiPost } from './api';
import type { UserRef } from './types';

export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED';
export type ApprovalStepStatus = 'WAITING' | 'PENDING' | 'APPROVED' | 'REJECTED' | 'SKIPPED';
export type ApprovalDecision = 'approve' | 'reject';

export interface ApprovalStep {
  level: number;
  status: ApprovalStepStatus;
  approver_role: { id: number; name: string } | null;
  approver_user: UserRef | null;
  acted_by: UserRef | null;
  acted_at: string | null;
  comment: string | null;
}

export interface ApprovalDocument {
  number: string;
  title: string;
  currency: string;
  /** Frontend route of the document. */
  path: string;
}

export interface ApprovalRequest {
  id: number;
  object_type: string;
  object_id: number;
  amount: string;
  status: ApprovalStatus;
  requested_by: UserRef;
  requested_at: string;
  completed_at: string | null;
  current_level: number | null;
  /** The signed-in user may approve or reject the current step. */
  can_act: boolean;
  document: ApprovalDocument | null;
  steps: ApprovalStep[];
}

export const approvalKeys = {
  all: ['approvals'] as const,
  inbox: ['approvals', 'inbox'] as const,
  history: (objectType: string, objectId: number) => ['approvals', 'history', objectType, objectId] as const,
};

const INBOX_REFRESH_MS = 60_000;

/** Requests waiting for a decision of the signed-in user; refreshed every minute. */
export function useApprovalInbox() {
  return useQuery({
    queryKey: approvalKeys.inbox,
    queryFn: ({ signal }) => apiGet<ApprovalRequest[]>('/approvals/inbox', undefined, signal),
    refetchInterval: INBOX_REFRESH_MS,
  });
}

/** All approval requests of one document, in the order the server returns them. */
export function useApprovalHistory(objectType: string, objectId: number) {
  return useQuery({
    queryKey: approvalKeys.history(objectType, objectId),
    queryFn: ({ signal }) =>
      apiGet<ApprovalRequest[]>('/approvals/history', { object_type: objectType, object_id: objectId }, signal),
  });
}

interface ApprovalAction {
  requestId: number;
  decision: ApprovalDecision;
  comment: string | null;
}

/** Approves or rejects the current step of a request and refreshes inbox and histories. */
export function useApprovalAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, decision, comment }: ApprovalAction) =>
      apiPost<ApprovalRequest>(`/approvals/${requestId}/${decision}`, { comment }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: approvalKeys.all }),
  });
}
