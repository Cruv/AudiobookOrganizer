import { useEffect, useState } from 'react';
import { ChevronUp, Folder, FolderOpen, Loader2, X } from 'lucide-react';
import { browse } from '@/api/client';
import type { BrowseResult } from '@/types';

interface Props {
  initialPath?: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

export default function DirectoryBrowser({ initialPath = '/', onSelect, onClose }: Props) {
  const [result, setResult] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPath = async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await browse(path);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to browse directory');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPath(initialPath);
  }, [initialPath]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        className="w-full max-w-lg rounded-lg border flex flex-col"
        style={{
          backgroundColor: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
          maxHeight: '80vh',
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <h2 className="text-lg font-semibold">Browse Directory</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--color-surface-hover)]">
            <X size={20} />
          </button>
        </div>

        {/* Current path + up button */}
        <div
          className="flex items-center gap-2 px-4 py-2 border-b text-sm"
          style={{ borderColor: 'var(--color-border)' }}
        >
          {result?.parent_path != null && (
            <button
              onClick={() => loadPath(result.parent_path!)}
              className="p-1 rounded hover:bg-[var(--color-surface-hover)]"
              title="Go up"
            >
              <ChevronUp size={18} />
            </button>
          )}
          <span className="font-mono text-xs truncate" style={{ color: 'var(--color-text-muted)' }}>
            {result?.current_path || '/'}
          </span>
        </div>

        {/* Directory listing */}
        <div className="flex-1 overflow-y-auto p-2" style={{ minHeight: '200px' }}>
          {loading && (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={24} className="animate-spin" style={{ color: 'var(--color-text-muted)' }} />
            </div>
          )}
          {error && (
            <p className="text-sm p-3" style={{ color: 'var(--color-danger)' }}>{error}</p>
          )}
          {!loading && !error && result && result.directories.length === 0 && (
            <p className="text-sm p-3" style={{ color: 'var(--color-text-muted)' }}>No subdirectories</p>
          )}
          {!loading && !error && result?.directories.map((dir) => (
            <button
              key={dir.path}
              onClick={() => loadPath(dir.path)}
              className="w-full flex items-center gap-2 px-3 py-2 rounded text-sm text-left hover:bg-[var(--color-surface-hover)]"
            >
              {dir.has_children ? (
                <FolderOpen size={16} style={{ color: 'var(--color-primary)' }} />
              ) : (
                <Folder size={16} style={{ color: 'var(--color-primary)' }} />
              )}
              <span className="truncate">{dir.name}</span>
            </button>
          ))}
        </div>

        {/* Footer */}
        <div
          className="flex justify-between items-center gap-2 p-4 border-t"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <span className="text-xs truncate font-mono" style={{ color: 'var(--color-text-muted)' }}>
            {result?.current_path || '/'}
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded text-sm border"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            >
              Cancel
            </button>
            <button
              onClick={() => result && onSelect(result.current_path)}
              disabled={!result}
              className="px-4 py-2 rounded text-sm font-medium text-white disabled:opacity-50"
              style={{ backgroundColor: 'var(--color-primary)' }}
            >
              Select This Directory
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
