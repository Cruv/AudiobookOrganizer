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

export function usePreviewPattern(pattern: string) {
  return useQuery({
    queryKey: ['pattern-preview', pattern],
    queryFn: () => api.previewPattern(pattern),
    enabled: pattern.length > 0,
  });
}
