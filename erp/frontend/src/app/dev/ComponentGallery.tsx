import { PlusOutlined } from '@ant-design/icons';
import { App, Button, Card, Col, Flex, Form, Row, Switch, theme, Typography } from 'antd';
import { type Key, type ReactNode, useState } from 'react';

import {
  ApprovalPanel,
  AttachmentList,
  BarcodeInput,
  ConfirmButton,
  DateInput,
  DownloadButton,
  EntitySelect,
  type LineColumn,
  LinesEditor,
  MoneyInput,
  PageHeader,
  PctInput,
  PriceInput,
  QtyInput,
  ServerTable,
  type ServerTableColumn,
  type ServerTableFilter,
  type StatusMap,
  StatusTag,
} from '@/components';
import { mul, pctOf, round, sum } from '@/lib/decimal';
import type { LineErrors } from '@/lib/forms';
import { fmtDateTime, fmtMoney, fmtPrice, fmtQty } from '@/lib/format';

import { DEV_OBJECT_ID, DEV_OBJECT_TYPE, installSampleApi, type SampleMaterial, type SampleMaterialType } from './sampleApi';

installSampleApi();

const MATERIAL_TYPES: StatusMap<SampleMaterialType> = {
  HAMMADDE: { label: 'Hammadde', color: 'blue' },
  YARI_MAMUL: { label: 'Yarı mamul', color: 'purple' },
  MAMUL: { label: 'Mamul', color: 'green' },
  TICARI_MAL: { label: 'Ticari mal', color: 'gold' },
  SARF: { label: 'Sarf malzemesi', color: 'default' },
};

type DocumentStatus = 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED' | 'CANCELLED';

const DOCUMENT_STATUS: StatusMap<DocumentStatus> = {
  DRAFT: { label: 'Taslak', color: 'default' },
  PENDING_APPROVAL: { label: 'Onay bekliyor', color: 'gold' },
  APPROVED: { label: 'Onaylandı', color: 'green' },
  REJECTED: { label: 'Reddedildi', color: 'red' },
  CANCELLED: { label: 'İptal edildi', color: 'default' },
};

const materialLabel = (material: SampleMaterial): string => `${material.code} — ${material.name}`;

const TABLE_COLUMNS: ServerTableColumn<SampleMaterial>[] = [
  { dataIndex: 'code', title: 'Kod', sortable: true, width: 110 },
  { dataIndex: 'name', title: 'Malzeme adı', sortable: true },
  {
    dataIndex: 'material_type',
    title: 'Tür',
    width: 130,
    render: (value) => <StatusTag map={MATERIAL_TYPES} value={value} />,
  },
  {
    dataIndex: 'stock_qty',
    title: 'Stok',
    align: 'right',
    sortable: true,
    width: 120,
    render: (value, row) => `${fmtQty(value, row.uom_decimals)} ${row.uom}`,
  },
  { dataIndex: 'price', title: 'Birim fiyat', align: 'right', sortable: true, width: 130, render: (value) => fmtPrice(value) },
  { key: 'value', title: 'Stok değeri', align: 'right', width: 140, render: (row) => fmtMoney(mul(row.stock_qty, row.price), 'TRY') },
  { dataIndex: 'is_active', title: 'Aktif', width: 70, render: (value) => (value ? 'Evet' : 'Hayır') },
  { dataIndex: 'created_at', title: 'Oluşturulma', sortable: true, width: 140, render: (value) => fmtDateTime(value) },
];

const TABLE_FILTERS: ServerTableFilter[] = [
  {
    type: 'select',
    name: 'material_type',
    label: 'Tür',
    multiple: true,
    options: Object.entries(MATERIAL_TYPES).map(([value, { label }]) => ({ value, label })),
  },
  { type: 'boolean', name: 'is_active', label: 'Aktif' },
  { type: 'text', name: 'code', label: 'Kod içerir' },
  { type: 'dateRange', name: 'created_from', toName: 'created_to', label: 'Oluşturulma' },
];

interface SampleLine {
  id?: number;
  material_id: number | null;
  description: string;
  tax_code: string | null;
  quantity: string | null;
  unit_price: string | null;
  discount_pct: string | null;
  freight: string | null;
  lead_days: number | null;
  delivery_date: string | null;
}

const TAX_CODES = [
  { value: 'IND0', label: 'IND0 · %0' },
  { value: 'IND10', label: 'IND10 · %10' },
  { value: 'IND20', label: 'IND20 · %20' },
];

function lineNet(line: SampleLine): ReturnType<typeof round> {
  const gross = mul(line.quantity, line.unit_price);
  return round(gross.minus(pctOf(gross, line.discount_pct)).plus(line.freight ?? 0), 2);
}

const LINE_COLUMNS: LineColumn<SampleLine>[] = [
  {
    editor: 'entity',
    field: 'material_id',
    title: 'Malzeme',
    required: true,
    width: 220,
    endpoint: '/_dev/materials',
    getLabel: materialLabel,
    params: { is_active: true },
    onSelect: (material: SampleMaterial | null) => ({
      description: material?.name ?? '',
      unit_price: material?.price ?? null,
    }),
  },
  { editor: 'text', field: 'description', title: 'Açıklama', maxLength: 120 },
  { editor: 'select', field: 'tax_code', title: 'KDV', width: 130, options: TAX_CODES },
  { editor: 'qty', field: 'quantity', title: 'Miktar', required: true, width: 100, align: 'right' },
  { editor: 'price', field: 'unit_price', title: 'Birim fiyat', required: true, width: 120, align: 'right' },
  { editor: 'pct', field: 'discount_pct', title: 'İskonto', width: 90, align: 'right' },
  {
    editor: 'money',
    field: 'freight',
    title: 'Navlun',
    width: 110,
    align: 'right',
    total: (rows) => fmtMoney(sum(rows.map((row) => row.freight))),
  },
  { editor: 'number', field: 'lead_days', title: 'Termin (gün)', width: 90, align: 'right' },
  { editor: 'date', field: 'delivery_date', title: 'Teslim tarihi', width: 125 },
  {
    editor: 'readonly',
    key: 'net',
    title: 'Net tutar',
    width: 120,
    align: 'right',
    render: (row) => fmtMoney(lineNet(row)),
    total: (rows) => fmtMoney(sum(rows.map(lineNet)), 'TRY'),
  },
];

const INITIAL_LINES: SampleLine[] = [
  {
    id: 501,
    material_id: 1,
    description: 'Çelik Sac 2 mm / 1',
    tax_code: 'IND20',
    quantity: '125.500',
    unit_price: '48.750000',
    discount_pct: '5.0000',
    freight: '350.00',
    lead_days: 7,
    delivery_date: '2025-04-02',
  },
  {
    id: 502,
    material_id: 2,
    description: 'Rulman 6204 / 1',
    tax_code: 'IND20',
    quantity: '40.000',
    unit_price: '173.007919',
    discount_pct: null,
    freight: null,
    lead_days: 14,
    delivery_date: null,
  },
  {
    id: 503,
    material_id: null,
    description: '',
    tax_code: null,
    quantity: null,
    unit_price: null,
    discount_pct: null,
    freight: null,
    lead_days: null,
    delivery_date: null,
  },
];

const SAMPLE_LINE_ERRORS: LineErrors = {
  2: { material_id: 'Malzeme seçilmelidir', quantity: 'Miktar sıfırdan büyük olmalıdır' },
};

function emptyLine(): SampleLine {
  return {
    material_id: null,
    description: '',
    tax_code: 'IND20',
    quantity: null,
    unit_price: null,
    discount_pct: null,
    freight: null,
    lead_days: null,
    delivery_date: null,
  };
}

interface InputsForm {
  amount: string | null;
  quantity: string | null;
  pieces: string | null;
  unit_price: string | null;
  discount_pct: string | null;
  posting_date: string | null;
  material_id: number | null;
  other_material_id: number | null;
}

interface LinesForm {
  lines: SampleLine[];
}

function Section({ title, children }: { title: string; children: ReactNode }): ReactNode {
  return (
    <Card size="small" title={title}>
      {children}
    </Card>
  );
}

/** Development-only page that renders every shared component against in-memory sample data. */
export function Component(): ReactNode {
  const { message } = App.useApp();
  const { token } = theme.useToken();
  const [inputsForm] = Form.useForm<InputsForm>();
  const [linesForm] = Form.useForm<LinesForm>();
  const inputValues = Form.useWatch([], inputsForm);
  const lineValues = Form.useWatch('lines', linesForm);
  const [linesDisabled, setLinesDisabled] = useState(false);
  const [showLineErrors, setShowLineErrors] = useState(true);
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [scans, setScans] = useState<string[]>([]);

  return (
    <div style={{ minHeight: '100vh', padding: 16, background: token.colorBgLayout }}>
      <PageHeader
        title="Bileşen Galerisi"
        subtitle="Yalnızca geliştirme ortamında, örnek verilerle"
        tags={<StatusTag map={DOCUMENT_STATUS} value="PENDING_APPROVAL" />}
        extra={
          <>
            <DownloadButton url="/_dev/report/pdf" format="pdf" />
            <DownloadButton url="/_dev/report/pdf" format="xlsx">
              Excel’e aktar
            </DownloadButton>
            <ConfirmButton
              danger
              confirmTitle="Belge iptal edilsin mi?"
              confirmDescription="Bu işlem geri alınamaz."
              onConfirm={() => void message.success('İptal edildi (örnek)')}
            >
              İptal et
            </ConfirmButton>
            <Button type="primary" icon={<PlusOutlined />}>
              Yeni kayıt
            </Button>
          </>
        }
      >
        <Flex gap={8} wrap>
          {(Object.keys(DOCUMENT_STATUS) as DocumentStatus[]).map((status) => (
            <StatusTag key={status} map={DOCUMENT_STATUS} value={status} />
          ))}
        </Flex>
      </PageHeader>

      <Flex vertical gap={12}>
        <Section title="Sayı, tarih ve seçim alanları">
          <Form<InputsForm>
            form={inputsForm}
            name="inputs"
            layout="vertical"
            initialValues={{
              amount: '1234.50',
              quantity: '12.500',
              pieces: '8',
              unit_price: '48.750000',
              discount_pct: '12.5000',
              posting_date: '2025-03-15',
              material_id: 42,
              other_material_id: null,
            }}
          >
            <Row gutter={12}>
              <Col xs={12} md={6} xl={3}>
                <Form.Item name="amount" label="Tutar (MoneyInput)">
                  <MoneyInput currency="TRY" />
                </Form.Item>
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Form.Item name="quantity" label="Miktar (QtyInput, 3)">
                  <QtyInput unit="KG" />
                </Form.Item>
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Form.Item name="pieces" label="Adet (QtyInput, 0)">
                  <QtyInput decimals={0} unit="ADET" />
                </Form.Item>
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Form.Item name="unit_price" label="Birim fiyat (PriceInput)">
                  <PriceInput />
                </Form.Item>
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Form.Item name="discount_pct" label="İskonto (PctInput)">
                  <PctInput />
                </Form.Item>
              </Col>
              <Col xs={12} md={6} xl={3}>
                <Form.Item name="posting_date" label="Tarih (DateInput)">
                  <DateInput />
                </Form.Item>
              </Col>
              <Col xs={24} md={12} xl={3}>
                <Form.Item name="material_id" label="Malzeme (EntitySelect)">
                  <EntitySelect<SampleMaterial> endpoint="/_dev/materials" getLabel={materialLabel} />
                </Form.Item>
              </Col>
              <Col xs={24} md={12} xl={3}>
                <Form.Item name="other_material_id" label="Yalnızca hammadde">
                  <EntitySelect<SampleMaterial>
                    endpoint="/_dev/materials"
                    getLabel={materialLabel}
                    params={{ material_type: 'HAMMADDE' }}
                    placeholder="Hammadde seçin"
                  />
                </Form.Item>
              </Col>
            </Row>
          </Form>
          <Typography.Text type="secondary">Form değerleri (API’ye gidecek biçim):</Typography.Text>
          <pre id="dev-input-values" style={{ margin: 0, fontSize: 12 }}>
            {JSON.stringify(inputValues)}
          </pre>
        </Section>

        <Section title="BarcodeInput">
          <Flex gap={12} align="center" wrap>
            <BarcodeInput
              captureGlobal
              style={{ width: 320 }}
              onScan={(code) => setScans((previous) => [code, ...previous].slice(0, 5))}
            />
            <Typography.Text id="dev-scans" type="secondary">
              {scans.length > 0 ? `Okutulanlar: ${scans.join(', ')}` : 'Henüz okutma yapılmadı'}
            </Typography.Text>
          </Flex>
        </Section>

        <Section title="LinesEditor">
          <Flex gap={16} align="center" style={{ marginBottom: 8 }}>
            <span>
              <Switch size="small" checked={linesDisabled} onChange={setLinesDisabled} aria-label="Salt okunur" /> Salt okunur
            </span>
            <span>
              <Switch size="small" checked={showLineErrors} onChange={setShowLineErrors} aria-label="Hata örneği" /> Hata
              örneği
            </span>
          </Flex>
          <Form<LinesForm> form={linesForm} name="lines" initialValues={{ lines: INITIAL_LINES }}>
            <Form.Item name="lines" style={{ marginBottom: 0 }}>
              <LinesEditor<SampleLine>
                columns={LINE_COLUMNS}
                createRow={emptyLine}
                disabled={linesDisabled}
                errors={showLineErrors ? SAMPLE_LINE_ERRORS : undefined}
              />
            </Form.Item>
          </Form>
          <pre id="dev-line-values" style={{ margin: '8px 0 0', fontSize: 12, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(lineValues)}
          </pre>
        </Section>

        <Section title="ServerTable">
          <ServerTable<SampleMaterial>
            endpoint="/_dev/materials"
            columns={TABLE_COLUMNS}
            filters={TABLE_FILTERS}
            defaultSort="code"
            defaultPageSize={20}
            searchPlaceholder="Kod veya ad ara"
            toolbar={
              <>
                <Typography.Text type="secondary">{selectedKeys.length} satır seçili</Typography.Text>
                <Button type="primary" icon={<PlusOutlined />}>
                  Yeni malzeme
                </Button>
              </>
            }
            selection={{
              selectedKeys,
              onChange: setSelectedKeys,
              isDisabled: (row) => !row.is_active,
            }}
            onRowClick={(row) => void message.info(`Satıra tıklandı: ${row.code}`)}
          />
        </Section>

        <Section title="ServerTable — hata durumu">
          <ServerTable<SampleMaterial>
            endpoint="/_dev/broken"
            columns={TABLE_COLUMNS.slice(0, 3)}
            urlState={false}
            searchable={false}
          />
        </Section>

        <Row gutter={12}>
          <Col xs={24} lg={12}>
            <Section title="ApprovalPanel">
              <ApprovalPanel
                objectType={DEV_OBJECT_TYPE}
                objectId={DEV_OBJECT_ID}
                onDecided={(request) => void message.info(`Talep durumu: ${request.status}`)}
              />
            </Section>
          </Col>
          <Col xs={24} lg={12}>
            <Section title="AttachmentList">
              <AttachmentList objectType={DEV_OBJECT_TYPE} objectId={DEV_OBJECT_ID} />
            </Section>
          </Col>
        </Row>
      </Flex>
    </div>
  );
}
