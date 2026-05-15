import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from '@/api/client';

export function useScans() {
  return useQuery({
    queryKey: ['scans'],
    queryFn: api.getScans,
  });
}

export function useScan(id: number | null) {
  const qc = useQueryClient();
  const lastStatus = useRef<string | null>(null);

  const query = useQuery({
    queryKey: ['scans', id],
    queryFn: () => api.getScan(id!),
    enabled: id != null,
    refetchInterval: (q) => {
      const data = q.state.data;
      if (data && data.status === 'running') return 1500;
      return false;
    },
  });

  // When polling transitions from "running" to anything else, invalidate
  // the scans list so the ScanPage's history table shows the new
  // status without a manual refresh. Without this the parent list
  // stayed stale until the user navigated away and back.
  useEffect(() => {
    const status = query.data?.status ?? null;
    if (lastStatus.current === 'running' && status && status !== 'running') {
      qc.invalidateQueries({ queryKey: ['scans'] });
      // Also invalidate books — a scan completing means new rows are
      // visible on the Review page.
      qc.invalidateQueries({ queryKey: ['books'] });
    }
    lastStatus.current = status;
  }, [query.data?.status, qc]);

  return query;
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
