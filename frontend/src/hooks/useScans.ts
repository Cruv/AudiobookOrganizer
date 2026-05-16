import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from '@/api/client';
import type { ScanDetail } from '@/types';

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

/**
 * Subscribe to a scan's server-sent events stream. Drops the noisy
 * 1.5s poll for the running case — we get a server-initiated update
 * whenever the scan's status / processed_folders / status_detail
 * actually changes.
 *
 * If the browser doesn't support EventSource (rare), or the request
 * 404s mid-stream, falls back to polling via `useScan`. Returns the
 * scan snapshot the same way useScan would so it's a drop-in.
 */
export function useScanEvents(id: number | null): {
  data: ScanDetail | undefined;
} {
  const qc = useQueryClient();
  const [snapshot, setSnapshot] = useState<ScanDetail | undefined>(undefined);

  useEffect(() => {
    if (id == null) {
      setSnapshot(undefined);
      return;
    }

    // Seed from the cache so we don't flicker on mount.
    const cached = qc.getQueryData<ScanDetail>(['scans', id]);
    if (cached) setSnapshot(cached);

    let cancelled = false;
    const source = new EventSource(`/api/scans/${id}/events`);

    const handleSnapshot = (raw: string) => {
      try {
        const data = JSON.parse(raw);
        if (cancelled) return;
        setSnapshot((prev) => {
          // The stream emits the small status snapshot. Merge with
          // whatever ScanDetail fields we already had cached so the
          // folder list etc. stays intact.
          const merged = { ...(prev || {}), ...data } as ScanDetail;
          qc.setQueryData(['scans', id], merged);
          return merged;
        });
      } catch {
        // ignore malformed event
      }
    };

    source.addEventListener('update', (e) => {
      handleSnapshot((e as MessageEvent).data);
    });
    source.addEventListener('complete', (e) => {
      handleSnapshot((e as MessageEvent).data);
      source.close();
      qc.invalidateQueries({ queryKey: ['scans'] });
      qc.invalidateQueries({ queryKey: ['books'] });
    });
    source.addEventListener('error', () => {
      // EventSource has its own auto-reconnect for transient failures;
      // close on hard error and let useScan's poll take over.
      source.close();
    });
    source.addEventListener('timeout', () => {
      source.close();
    });

    return () => {
      cancelled = true;
      source.close();
    };
  }, [id, qc]);

  return { data: snapshot };
}
