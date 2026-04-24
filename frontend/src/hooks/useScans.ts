import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from '@/api/client';

export function useScans() {
  return useQuery({
    queryKey: ['scans'],
    queryFn: api.getScans,
  });
}

export function useScan(id: number | null) {
  return useQuery({
    queryKey: ['scans', id],
    queryFn: () => api.getScan(id!),
    enabled: id != null,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && data.status === 'running') return 1500;
      return false;
    },
  });
}

export function useCreateScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.createScan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans'] }),
  });
}

export function useReimportLibrary() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.reimportLibrary,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans'] }),
  });
}

export function useDeleteScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteScan,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scans'] }),
  });
}
