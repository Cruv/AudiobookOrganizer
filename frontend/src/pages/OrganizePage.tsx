import { useState } from 'react';
import { FolderOutput, Loader2, Eye } from 'lucide-react';
import { useBooks } from '@/hooks/useBooks';
import * as api from '@/api/client';
import type { OrganizePreviewItem } from '@/types';
import ConfidenceBadge from '@/components/ConfidenceBadge';

export default function OrganizePage() {
  const { data: books, isLoading, refetch } = useBooks({
    confirmed: true,
    organize_status: 'pending',
  });
  const { data: organizedBooks } = useBooks({ organize_status: 'copied' });

  const [previews, setPreviews] = useState<OrganizePreviewItem[]>([]);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isOrganizing, setIsOrganizing] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (!books) return;
    setSelected(new Set(books.map((b) => b.id)));
  };

  const handlePreview = async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    setIsPreviewing(true);
    try {
      const resp = await api.previewOrganize(ids);
      setPreviews(resp.items);
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleOrganize = async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    setIsOrganizing(true);
    try {
      await api.executeOrganize(ids);
      // Poll until done
      const poll = setInterval(async () => {
        await refetch();
        const remaining = books?.filter(
          (b) => ids.includes(b.id) && b.organize_status === 'copying',
        );
        if (!remaining || remaining.length === 0) {
          clearInterval(poll);
          setIsOrganizing(false);
          setSelected(new Set());
          setPreviews([]);
          refetch();
        }
      }, 2000);
    } catch {
      setIsOrganizing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={32} className="animate-spin" style={{ color: 'var(--color-primary)' }} />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Organize</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
            {books?.length || 0} confirmed books ready to organize
            {organizedBooks && organizedBooks.length > 0 && (
              <> &middot; {organizedBooks.length} already organized</>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={selectAll}
            className="px-3 py-2 rounded text-sm border"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
          >
            Select All
          </button>
          <button
            onClick={handlePreview}
            disabled={selected.size === 0 || isPreviewing}
            className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {isPreviewing ? <Loader2 size={16} className="animate-spin" /> : <Eye size={16} />}
            Preview
          </button>
          <button
            onClick={handleOrganize}
            disabled={selected.size === 0 || isOrganizing}
            className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-success)' }}
          >
            {isOrganizing ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <FolderOutput size={16} />
            )}
            Organize ({selected.size})
          </button>
        </div>
      </div>

      {/* Preview results */}
      {previews.length > 0 && (
        <div
          className="rounded-lg border p-4 mb-6"
          style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          <h3 className="text-sm font-semibold mb-3">Path Preview</h3>
          <div className="space-y-2">
            {previews.map((p) => (
              <div key={p.book_id} className="text-xs">
                <span style={{ color: 'var(--color-text-muted)' }}>{p.title}</span>
                <span className="mx-2">&rarr;</span>
                <span className="font-mono" style={{ color: 'var(--color-success)' }}>
                  {p.destination_path}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Book list */}
      <div className="space-y-2">
        {books?.map((book) => (
          <div
            key={book.id}
            onClick={() => toggleSelect(book.id)}
            className="flex items-center gap-4 rounded-lg border px-4 py-3 cursor-pointer"
            style={{
              backgroundColor: selected.has(book.id) ? 'var(--color-surface-hover)' : 'var(--color-surface)',
              borderColor: selected.has(book.id) ? 'var(--color-primary)' : 'var(--color-border)',
            }}
          >
            <input
              type="checkbox"
              checked={selected.has(book.id)}
              onChange={() => toggleSelect(book.id)}
              className="flex-shrink-0"
            />
            <div className="flex-1 min-w-0">
              <span className="font-medium text-sm">{book.title || 'Unknown Title'}</span>
              <span className="text-xs ml-2" style={{ color: 'var(--color-text-muted)' }}>
                {book.author || 'Unknown Author'}
              </span>
              <ConfidenceBadge confidence={book.confidence} />
            </div>
          </div>
        ))}

        {books?.length === 0 && (
          <div
            className="text-center py-12 rounded-lg border"
            style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <p style={{ color: 'var(--color-text-muted)' }}>
              No confirmed books to organize. Go to Review to confirm books first.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
