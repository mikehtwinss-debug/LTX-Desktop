import { DeleteOutlined, DownloadOutlined, PaperClipOutlined, UploadOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, App, Button, Empty, Flex, List, Typography, Upload } from 'antd';
import { type ReactNode, useState } from 'react';

import { apiGet, apiPost, downloadFile, errorMessage, remove } from '@/lib/api';
import { fmtDateTime, fmtFileSize } from '@/lib/format';
import { queryKeys } from '@/lib/queryClient';
import type { UserRef } from '@/lib/types';

import { ConfirmButton } from './ConfirmButton';

const ENDPOINT = '/attachments';
const MAX_FILE_SIZE = 20 * 1024 * 1024;

export interface Attachment {
  id: number;
  filename: string;
  mime: string;
  size: number;
  created_at: string;
  uploaded_by?: UserRef | null;
}

export interface AttachmentListProps {
  /** Owner of the files, e.g. `PO` and the order id. */
  objectType: string;
  objectId: number;
  /** Hides upload and delete. */
  readOnly?: boolean;
}

/**
 * Files attached to a record: list, upload (20 MB per file), download and delete.
 *
 *   <AttachmentList objectType="PO" objectId={order.id} readOnly={!canEdit} />
 */
export function AttachmentList({ objectType, objectId, readOnly = false }: AttachmentListProps): ReactNode {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const params = { object_type: objectType, object_id: objectId };
  const listKey = queryKeys.list(ENDPOINT, params);

  const list = useQuery({
    queryKey: listKey,
    queryFn: ({ signal }) => apiGet<Attachment[]>(ENDPOINT, params, signal),
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append('object_type', objectType);
      form.append('object_id', String(objectId));
      form.append('file', file);
      return apiPost<Attachment>(ENDPOINT, form);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey }),
  });

  const removal = useMutation({
    mutationFn: (id: number) => remove(ENDPOINT, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: listKey }),
  });

  const handleUpload = (file: File): false => {
    if (file.size > MAX_FILE_SIZE) {
      void message.error(`${file.name}: dosya boyutu 20 MB sınırını aşıyor`);
    } else {
      upload.mutate(file);
    }
    // The file is sent through the API client; the upload component must not post it itself.
    return false;
  };

  const handleDownload = async (attachment: Attachment): Promise<void> => {
    setDownloadingId(attachment.id);
    try {
      await downloadFile(`${ENDPOINT}/${attachment.id}/download`);
    } catch (error) {
      void message.error(errorMessage(error));
    } finally {
      setDownloadingId(null);
    }
  };

  return (
    <Flex vertical gap={8}>
      {list.isError && (
        <Alert
          type="error"
          showIcon
          message={errorMessage(list.error)}
          action={
            <Button size="small" onClick={() => void list.refetch()}>
              Tekrar dene
            </Button>
          }
        />
      )}
      <List<Attachment>
        size="small"
        bordered
        loading={list.isPending}
        dataSource={list.data ?? []}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Ekli dosya yok" /> }}
        renderItem={(attachment) => (
          <List.Item
            actions={[
              <Button
                key="download"
                type="text"
                size="small"
                icon={<DownloadOutlined />}
                aria-label={`${attachment.filename} dosyasını indir`}
                loading={downloadingId === attachment.id}
                onClick={() => void handleDownload(attachment)}
              />,
              ...(readOnly
                ? []
                : [
                    <ConfirmButton
                      key="delete"
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      aria-label={`${attachment.filename} dosyasını sil`}
                      confirmTitle="Dosya silinsin mi?"
                      confirmDescription={attachment.filename}
                      onConfirm={() => removal.mutateAsync(attachment.id)}
                    />,
                  ]),
            ]}
          >
            <Flex align="center" gap={8} style={{ minWidth: 0 }}>
              <PaperClipOutlined />
              <Typography.Text ellipsis={{ tooltip: attachment.filename }} style={{ maxWidth: 360 }}>
                {attachment.filename}
              </Typography.Text>
              <Typography.Text type="secondary" style={{ whiteSpace: 'nowrap' }}>
                {[fmtFileSize(attachment.size), fmtDateTime(attachment.created_at), attachment.uploaded_by?.full_name]
                  .filter(Boolean)
                  .join(' · ')}
              </Typography.Text>
            </Flex>
          </List.Item>
        )}
      />
      {!readOnly && (
        <div>
          <Upload multiple showUploadList={false} beforeUpload={handleUpload}>
            <Button icon={<UploadOutlined />} loading={upload.isPending}>
              Dosya ekle
            </Button>
          </Upload>
        </div>
      )}
    </Flex>
  );
}
