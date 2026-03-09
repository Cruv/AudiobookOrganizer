import type {
  Book,
  BookDetail,
  BrowseResult,
  LookupResult,
  OrganizePreviewItem,
  PatternPreview,
  PurgeResultItem,
  PurgeVerifyItem,
  Scan,
  ScanDetail,
  Settings,
} from '@/types';

const BASE = '/api';

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${url}`, {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(error.detail || resp.statusText);
  }
  return resp.json();
}

// Browse
export const browse = (path: string) =>
  request<BrowseResult>(`/browse?path=${encodeURIComponent(path)}`);

// Scans
export const createScan = (source_dir: string) =>
  request<Scan>('/scans', {
    method: 'POST',
    body: JSON.stringify({ source_dir }),
  });

export const getScans = () => request<Scan[]>('/scans');

export const getScan = (id: number) => request<ScanDetail>(`/scans/${id}`);

export const deleteScan = (id: number) =>
  request<{ detail: string }>(`/scans/${id}`, { method: 'DELETE' });

// Books
export const getBooks = (params?: {
  scan_id?: number;
  confirmed?: boolean;
  organize_status?: string;
  purge_status?: string;
  sort?: string;
}) => {
  const searchParams = new URLSearchParams();
  if (params?.scan_id != null) searchParams.set('scan_id', String(params.scan_id));
  if (params?.confirmed != null) searchParams.set('confirmed', String(params.confirmed));
  if (params?.organize_status) searchParams.set('organize_status', params.organize_status);
  if (params?.purge_status) searchParams.set('purge_status', params.purge_status);
  if (params?.sort) searchParams.set('sort', params.sort);
  const qs = searchParams.toString();
  return request<Book[]>(`/books${qs ? `?${qs}` : ''}`);
};

export const getBook = (id: number) => request<BookDetail>(`/books/${id}`);

export const updateBook = (
  id: number,
  data: {
    title?: string;
    author?: string;
    series?: string | null;
    series_position?: string | null;
    year?: string | null;
    narrator?: string | null;
  },
) =>
  request<Book>(`/books/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

export const confirmBook = (id: number) =>
  request<Book>(`/books/${id}/confirm`, { method: 'POST' });

export const confirmBatch = (data: {
  book_ids?: number[];
  min_confidence?: number;
  scan_id?: number;
}) =>
  request<{ confirmed: number }>('/books/confirm-batch', {
    method: 'POST',
    body: JSON.stringify(data),
  });

export const lookupBook = (id: number) =>
  request<{ results: LookupResult[] }>(`/books/${id}/lookup`, { method: 'POST' });

export const searchBook = (id: number, query: string) =>
  request<{ results: LookupResult[] }>(`/books/${id}/search`, {
    method: 'POST',
    body: JSON.stringify({ query }),
  });

export const applyLookup = (
  id: number,
  data: { provider: string; result_index: number },
) =>
  request<Book>(`/books/${id}/apply-lookup`, {
    method: 'POST',
    body: JSON.stringify(data),
  });

// Export
export const exportBooks = async (scanId?: number) => {
  const params = scanId != null ? `?scan_id=${scanId}` : '';
  const resp = await fetch(`${BASE}/books/export${params}`);
  return resp.json();
};

// Organize
export const previewOrganize = (book_ids: number[]) =>
  request<{ items: OrganizePreviewItem[] }>('/organize/preview', {
    method: 'POST',
    body: JSON.stringify({ book_ids }),
  });

export const executeOrganize = (book_ids: number[]) =>
  request<{ detail: string; book_ids: number[] }>('/organize/execute', {
    method: 'POST',
    body: JSON.stringify({ book_ids }),
  });

export const getOrganizeStatus = (book_id: number) =>
  request<{
    book_id: number;
    organize_status: string;
    files_copied: number;
    files_total: number;
    files_failed: number;
  }>(`/organize/status/${book_id}`);

// Purge
export const verifyPurge = (book_ids: number[]) =>
  request<{ items: PurgeVerifyItem[] }>('/purge/verify', {
    method: 'POST',
    body: JSON.stringify({ book_ids }),
  });

export const executePurge = (book_ids: number[]) =>
  request<{ results: PurgeResultItem[] }>('/purge/execute', {
    method: 'POST',
    body: JSON.stringify({ book_ids }),
  });

// Settings
export const getSettings = () => request<Settings>('/settings');

export const updateSettings = (data: Partial<Settings>) =>
  request<Settings>('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  });

export const previewPattern = (pattern: string) =>
  request<PatternPreview>(`/settings/preview-pattern?pattern=${encodeURIComponent(pattern)}`);
