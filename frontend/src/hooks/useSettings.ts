import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from '@/api/client';
import type { Settings } from '@/types';

export function useSettings() {
  return useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Settings>) => api.updateSettings(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['settings'] }),
  });
}

/**
 * Debounced pattern preview. The Settings page pattern field is
 * mutated on every keystroke, but the /preview-pattern endpoint
 * doesn't need to fire that often. Internally debounces by 300ms
 * before issuing the network request.
 */
export function usePreviewPattern(pattern: string) {
  const [debounced, setDebounced] = useState(pattern);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(pattern), 300);
    return () => window.clearTimeout(id);
  }, [pattern]);

  return useQuery({
    queryKey: ['pattern-preview', debounced],
    queryFn: () => api.previewPattern(debounced),
    enabled: debounced.length > 0,
    staleTime: 60_000,
  });
}
