import { useEffect, useState } from 'react';
import { ChevronUp, Folder, FolderOpen, Loader2 } from 'lucide-react';
import { browse } from '@/api/client';
import type { BrowseResult } from '@/types';
import { Modal, Button } from '@/components/ui';

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
    <Modal
      title="Browse Directory"
      onClose={onClose}
      footer={
        <div className="flex justify-between items-center gap-2">
          <span className="text-xs truncate font-mono" style={{ color: 'var(--color-text-muted)' }}>
            {result?.current_path || '/'}
          </span>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button
              onClick={() => result && onSelect(result.current_path)}
              disabled={!result}
            >
              Select This Directory
            </Button>
          </div>
        </div>
      }
    >
      {/* Current path + up button */}
      <div className="flex items-center gap-2 mb-3 pb-3 border-b text-sm" style={{ borderColor: 'var(--color-border)' }}>
        {result?.parent_path != null && (
          <button
            onClick={() => loadPath(result.parent_path!)}
            className="p-1 rounded hover:bg-[var(--color-surface-hover)]"
            title="Go up"
            aria-label="Go to parent directory"
          >
            <ChevronUp size={18} />
          </button>
        )}
        <span className="font-mono text-xs truncate" style={{ color: 'var(--color-text-muted)' }}>
          {result?.current_path || '/'}
        </span>
      </div>

      {/* Directory listing */}
      <div style={{ minHeight: '200px' }}>
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
            className="w-full flex items-center gap-2 px-3 py-2 rounded text-sm text-left hover:bg-[var(--color-surface-hover)] transition-colors"
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
    </Modal>
  );
}
