import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';

import { api, type ListResult } from '@/lib/api';
import type { ApprovalRequest } from '@/lib/approvals';

/**
 * In-memory stand-in for the backend, used only by the development component gallery. It answers
 * the `/_dev/*` endpoints and the approval and attachment calls made for object type `DEV`;
 * every other request goes to the real backend.
 */

export const DEV_OBJECT_TYPE = 'DEV';
export const DEV_OBJECT_ID = 1;

const LATENCY_MS = 250;

export type SampleMaterialType = 'HAMMADDE' | 'YARI_MAMUL' | 'MAMUL' | 'TICARI_MAL' | 'SARF';

export interface SampleMaterial {
  id: number;
  code: string;
  name: string;
  material_type: SampleMaterialType;
  uom: string;
  uom_decimals: number;
  stock_qty: string;
  price: string;
  tax_rate: string;
  is_active: boolean;
  created_at: string;
}

const NAMES = [
  'Çelik Sac 2 mm',
  'Rulman 6204',
  'Hidrolik Yağ ISO 46',
  'M8 Cıvata',
  'Ambalaj Kolisi',
  'Alüminyum Profil 40×40',
  'Şanzıman Gövdesi',
  'İş Eldiveni',
  'Öğütme Diski',
  'Güç Kablosu 3×2,5',
];
const TYPES: SampleMaterialType[] = ['HAMMADDE', 'YARI_MAMUL', 'MAMUL', 'TICARI_MAL', 'SARF'];
const UNITS: [string, number][] = [
  ['KG', 3],
  ['ADET', 0],
  ['LT', 3],
  ['M', 2],
];

const materials: SampleMaterial[] = Array.from({ length: 137 }, (_, index) => {
  const [uom, uomDecimals] = UNITS[index % UNITS.length] ?? ['ADET', 0];
  return {
    id: index + 1,
    code: `MLZ-${String(index + 1).padStart(4, '0')}`,
    name: `${NAMES[index % NAMES.length]} / ${Math.floor(index / NAMES.length) + 1}`,
    material_type: TYPES[index % TYPES.length] ?? 'HAMMADDE',
    uom,
    uom_decimals: uomDecimals,
    stock_qty: uomDecimals === 0 ? `${(index * 37) % 500}.000` : `${(index * 37) % 500}.${String((index * 125) % 1000).padStart(3, '0')}`,
    price: `${(index * 173) % 9000}.${String((index * 7919) % 1000000).padStart(6, '0')}`,
    tax_rate: index % 7 === 0 ? '10.0000' : '20.0000',
    is_active: index % 9 !== 0,
    created_at: new Date(Date.UTC(2025, 0, 1 + index, 8, 30)).toISOString(),
  };
});

const requester = { id: 11, full_name: 'Ayşe Örnek' };
const manager = { id: 12, full_name: 'Mehmet Deneme' };

let approvals: ApprovalRequest[] = [
  {
    id: 900002,
    object_type: DEV_OBJECT_TYPE,
    object_id: DEV_OBJECT_ID,
    amount: '184500.00',
    status: 'PENDING',
    requested_by: requester,
    requested_at: '2025-03-14T08:05:00Z',
    completed_at: null,
    current_level: 2,
    can_act: true,
    document: { number: 'SIP0000042', title: 'Satınalma siparişi', currency: 'TRY', path: '/mm/siparis/42' },
    steps: [
      {
        level: 1,
        status: 'APPROVED',
        approver_role: { id: 3, name: 'Satınalma Müdürü' },
        approver_user: null,
        acted_by: manager,
        acted_at: '2025-03-14T09:40:00Z',
        comment: 'Bütçe dahilinde.',
      },
      {
        level: 2,
        status: 'PENDING',
        approver_role: { id: 5, name: 'Genel Müdür' },
        approver_user: null,
        acted_by: null,
        acted_at: null,
        comment: null,
      },
    ],
  },
  {
    id: 900001,
    object_type: DEV_OBJECT_TYPE,
    object_id: DEV_OBJECT_ID,
    amount: '197250.00',
    status: 'REJECTED',
    requested_by: requester,
    requested_at: '2025-03-10T13:20:00Z',
    completed_at: '2025-03-11T07:55:00Z',
    current_level: null,
    can_act: false,
    document: { number: 'SIP0000042', title: 'Satınalma siparişi', currency: 'TRY', path: '/mm/siparis/42' },
    steps: [
      {
        level: 1,
        status: 'REJECTED',
        approver_role: { id: 3, name: 'Satınalma Müdürü' },
        approver_user: null,
        acted_by: manager,
        acted_at: '2025-03-11T07:55:00Z',
        comment: 'Birim fiyatlar güncel teklifle uyuşmuyor, düzeltilsin.',
      },
      {
        level: 2,
        status: 'SKIPPED',
        approver_role: { id: 5, name: 'Genel Müdür' },
        approver_user: null,
        acted_by: null,
        acted_at: null,
        comment: null,
      },
    ],
  },
];

interface SampleAttachment {
  id: number;
  filename: string;
  mime: string;
  size: number;
  created_at: string;
  uploaded_by: { id: number; full_name: string };
}

let attachments: SampleAttachment[] = [
  {
    id: 910001,
    filename: 'Teklif - Örnek Metal Sanayi.pdf',
    mime: 'application/pdf',
    size: 248_312,
    created_at: '2025-03-12T10:15:00Z',
    uploaded_by: requester,
  },
  {
    id: 910002,
    filename: 'Teknik şartname.xlsx',
    mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    size: 18_944,
    created_at: '2025-03-12T10:18:00Z',
    uploaded_by: requester,
  },
];
let nextAttachmentId = 910003;

type Params = Record<string, unknown>;

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : '';
}

function listMaterials(params: Params): ListResult<SampleMaterial> {
  const q = text(params.q).toLocaleLowerCase('tr');
  const types = [params.material_type].flat().map(text).filter(Boolean);
  const active = text(params.is_active);
  const code = text(params.code).toLocaleLowerCase('tr');
  const from = text(params.created_from);
  const to = text(params.created_to);
  const rows = materials.filter(
    (row) =>
      (q === '' || `${row.code} ${row.name}`.toLocaleLowerCase('tr').includes(q)) &&
      (types.length === 0 || types.includes(row.material_type)) &&
      (active === '' || String(row.is_active) === active) &&
      (code === '' || row.code.toLocaleLowerCase('tr').includes(code)) &&
      (from === '' || row.created_at.slice(0, 10) >= from) &&
      (to === '' || row.created_at.slice(0, 10) <= to),
  );

  const sort = text(params.sort);
  const field = sort.replace(/^-/, '') as keyof SampleMaterial;
  if (sort !== '' && field in (materials[0] ?? {})) {
    const numeric = field === 'price' || field === 'stock_qty' || field === 'id';
    rows.sort((a, b) =>
      numeric ? Number(a[field]) - Number(b[field]) : String(a[field]).localeCompare(String(b[field]), 'tr'),
    );
    if (sort.startsWith('-')) {
      rows.reverse();
    }
  }

  const page = Number(params.page) || 1;
  const pageSize = Number(params.page_size) || 50;
  return { items: rows.slice((page - 1) * pageSize, page * pageSize), total: rows.length, page, page_size: pageSize };
}

interface Reply {
  status: number;
  data: unknown;
  headers?: Record<string, string>;
}

function apiError(status: number, code: string, message: string): Reply {
  return { status, data: { code, message, details: null } };
}

function decide(id: number, decision: string, body: unknown): Reply {
  const request = approvals.find((candidate) => candidate.id === id);
  if (!request) {
    return apiError(404, 'NOT_FOUND', 'Onay talebi bulunamadı.');
  }
  const comment = typeof body === 'string' ? ((JSON.parse(body) as { comment?: string | null }).comment ?? null) : null;
  const approved = decision === 'approve';
  const updated: ApprovalRequest = {
    ...request,
    status: approved ? 'APPROVED' : 'REJECTED',
    completed_at: new Date().toISOString(),
    current_level: null,
    can_act: false,
    steps: request.steps.map((step) =>
      step.status === 'PENDING'
        ? {
            ...step,
            status: approved ? 'APPROVED' : 'REJECTED',
            acted_by: { id: 13, full_name: 'Zeynep Numune' },
            acted_at: new Date().toISOString(),
            comment,
          }
        : step,
    ),
  };
  approvals = approvals.map((candidate) => (candidate.id === id ? updated : candidate));
  return { status: 200, data: updated };
}

function route(config: InternalAxiosRequestConfig): Reply | null {
  const method = (config.method ?? 'get').toLowerCase();
  const url = config.url ?? '';
  const params = (config.params ?? {}) as Params;

  if (url === '/_dev/materials') {
    return { status: 200, data: listMaterials(params) };
  }
  const material = /^\/_dev\/materials\/(\d+)$/.exec(url);
  if (material) {
    const found = materials.find((row) => row.id === Number(material[1]));
    return found ? { status: 200, data: found } : apiError(404, 'NOT_FOUND', 'Malzeme bulunamadı.');
  }
  if (url === '/_dev/broken') {
    return apiError(503, 'SERVICE_UNAVAILABLE', 'Örnek hata: liste şu anda yüklenemiyor.');
  }
  if (url === '/_dev/report/pdf') {
    return {
      status: 200,
      data: new Blob(['Örnek rapor içeriği'], { type: 'application/pdf' }),
      headers: { 'content-disposition': 'attachment; filename="ornek-rapor.pdf"' },
    };
  }

  if (url === '/approvals/history' && params.object_type === DEV_OBJECT_TYPE) {
    return { status: 200, data: approvals };
  }
  const decision = /^\/approvals\/(9\d{5})\/(approve|reject)$/.exec(url);
  if (decision && method === 'post') {
    return decide(Number(decision[1]), decision[2] ?? '', config.data);
  }

  if (url === '/attachments' && method === 'get' && params.object_type === DEV_OBJECT_TYPE) {
    return { status: 200, data: attachments };
  }
  if (url === '/attachments' && method === 'post' && config.data instanceof FormData) {
    const form = config.data;
    const file = form.get('file');
    if (form.get('object_type') === DEV_OBJECT_TYPE && file instanceof File) {
      const created: SampleAttachment = {
        id: nextAttachmentId++,
        filename: file.name,
        mime: file.type,
        size: file.size,
        created_at: new Date().toISOString(),
        uploaded_by: requester,
      };
      attachments = [...attachments, created];
      return { status: 201, data: created };
    }
  }
  const attachment = /^\/attachments\/(91\d{4})(\/download)?$/.exec(url);
  if (attachment) {
    const found = attachments.find((item) => item.id === Number(attachment[1]));
    if (!found) {
      return apiError(404, 'NOT_FOUND', 'Dosya bulunamadı.');
    }
    if (attachment[2] && method === 'get') {
      return {
        status: 200,
        data: new Blob([`Örnek dosya: ${found.filename}`], { type: found.mime }),
        headers: { 'content-disposition': `attachment; filename*=UTF-8''${encodeURIComponent(found.filename)}` },
      };
    }
    if (method === 'delete') {
      attachments = attachments.filter((item) => item.id !== found.id);
      return { status: 204, data: null };
    }
  }
  return null;
}

function settle(config: InternalAxiosRequestConfig, reply: Reply): Promise<AxiosResponse> {
  const response: AxiosResponse = {
    data: reply.data,
    status: reply.status,
    statusText: String(reply.status),
    headers: reply.headers ?? {},
    config,
  };
  return new Promise((resolve, reject) => {
    window.setTimeout(() => {
      if (reply.status < 400) {
        resolve(response);
      } else {
        reject(new AxiosError(`Request failed with status code ${reply.status}`, AxiosError.ERR_BAD_RESPONSE, config, null, response));
      }
    }, LATENCY_MS);
  });
}

let installed = false;

/** Routes the gallery's requests to the sample data. Safe to call more than once. */
export function installSampleApi(): void {
  if (installed) {
    return;
  }
  installed = true;
  const backend = axios.getAdapter(api.defaults.adapter);
  api.defaults.adapter = (config) => {
    const reply = route(config);
    return reply ? settle(config, reply) : backend(config);
  };
}
