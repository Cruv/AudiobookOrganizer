import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from '@/api/client';

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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['books'] }),
  });
}

export function useUnconfirmBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.unconfirmBatch,
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
