import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from '@/api/client';
import type { Book, PaginatedBooks } from '@/types';

export function useBooks(params?: {
  scan_id?: number;
  confirmed?: boolean;
  organize_status?: string;
  purge_status?: string;
  sort?: string;
  page?: number;
  page_size?: number;
  edition?: string;
  min_confidence?: number;
  max_confidence?: number;
  search?: string;
}) {
  return useQuery({
    queryKey: ['books', params],
    queryFn: () => api.getBooks(params),
    staleTime: 0,
  });
}

/**
 * Patch a single book inside every cached PaginatedBooks result. Used
 * for optimistic confirm/lock/unconfirm/unlock — avoids refetching the
 * whole list on every click.
 *
 * The TanStack Query queryClient.setQueriesData lets us touch every
 * cached variant of ['books', params] in one call. We DON'T invalidate
 * afterwards because the backend response is the source of truth and
 * we'll patch again with the real result.
 */
function patchBookInCaches(
  qc: ReturnType<typeof useQueryClient>,
  book: Book,
) {
  qc.setQueriesData<PaginatedBooks>({ queryKey: ['books'] }, (old) => {
    if (!old || !old.items) return old;
    let touched = false;
    const items = old.items.map((b) => {
      if (b.id !== book.id) return b;
      touched = true;
      return { ...b, ...book };
    });
    return touched ? { ...old, items } : old;
  });
}

export function useBook(id: number) {
  return useQuery({
    queryKey: ['books', id],
    queryFn: () => api.getBook(id),
    enabled: id > 0,
  });
}

export function useUpdateBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof api.updateBook>[1] }) =>
      api.updateBook(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useConfirmBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.confirmBook(id),
    onSuccess: (book) => patchBookInCaches(qc, book),
  });
}

export function useConfirmBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.confirmBatch,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useUnconfirmBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.unconfirmBook(id),
    onSuccess: (book) => patchBookInCaches(qc, book),
  });
}

export function useUnconfirmBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.unconfirmBatch,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useDeleteBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteBook(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useLookupBook() {
  return useMutation({
    mutationFn: (id: number) => api.lookupBook(id),
  });
}

export function useSearchBook() {
  return useMutation({
    mutationFn: ({ id, query }: { id: number; query: string }) =>
      api.searchBook(id, query),
  });
}

export function useApplyLookup() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: number;
      data: { provider: string; result_index: number };
    }) => api.applyLookup(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useCandidates(bookId: number, includeRejected = false) {
  return useQuery({
    queryKey: ['candidates', bookId, includeRejected],
    queryFn: () => api.getCandidates(bookId, includeRejected),
    enabled: bookId > 0,
  });
}

export function useRelookupBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, autoApply = true }: { id: number; autoApply?: boolean }) =>
      api.relookupBook(id, autoApply),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['candidates', vars.id] });
      qc.invalidateQueries({ queryKey: ['books'] });
    },
  });
}

export function useRelookupBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ book_ids, auto_apply = true }: { book_ids: number[]; auto_apply?: boolean }) =>
      api.relookupBatch(book_ids, auto_apply),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['books'] });
      qc.invalidateQueries({ queryKey: ['candidates'] });
    },
  });
}

export function useApplyCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ bookId, candidateId }: { bookId: number; candidateId: number }) =>
      api.applyCandidate(bookId, candidateId),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['candidates', vars.bookId] });
      qc.invalidateQueries({ queryKey: ['books'] });
    },
  });
}

export function useRejectCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ bookId, candidateId }: { bookId: number; candidateId: number }) =>
      api.rejectCandidate(bookId, candidateId),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['candidates', vars.bookId] });
      qc.invalidateQueries({ queryKey: ['books'] });
    },
  });
}

export function useLockBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.lockBook(id),
    onSuccess: (book) => patchBookInCaches(qc, book),
  });
}

export function useUnlockBook() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.unlockBook(id),
    onSuccess: (book) => patchBookInCaches(qc, book),
  });
}

export function useBulkUpdateBooks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      book_ids,
      patch,
    }: {
      book_ids: number[];
      patch: Record<string, string | boolean | null>;
    }) => api.bulkUpdateBooks(book_ids, patch),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useMarkOrganized() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.markOrganized(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useMarkOrganizedBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (book_ids: number[]) => api.markOrganizedBatch(book_ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}
