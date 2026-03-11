import { useState } from 'react';
import { Loader2, ShieldCheck, Trash2 } from 'lucide-react';
import { useBooks } from '@/hooks/useBooks';
import * as api from '@/api/client';
import ConfirmDialog from '@/components/ConfirmDialog';
import { useToast } from '@/components/Toast';
import type { PurgeVerifyItem } from '@/types';

export default function PurgePage() {
  const { data: booksData, isLoading, refetch } = useBooks({
    organize_status: 'copied',
    purge_status: 'not_purged',
    page_size: 200,
  });
  const books = booksData?.items;
  const toast = useToast();

  const [verifications, setVerifications] = useState<Map<number, PurgeVerifyItem>>(new Map());
  const [isVerifying, setIsVerifying] = useState(false);
  const [isPurging, setIsPurging] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleVerify = async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    setIsVerifying(true);
    try {
      const resp = await api.verifyPurge(ids);
      const map = new Map<number, PurgeVerifyItem>();
      for (const item of resp.items) {
        map.set(item.book_id, item);
      }
      setVerifications(map);
    } finally {
      setIsVerifying(false);
    }
  };

  const handlePurge = async () => {
    const ids = Array.from(selected).filter((id) => verifications.get(id)?.verified);
    if (ids.length === 0) return;
    setIsPurging(true);
    setShowConfirm(false);
    try {
      await api.executePurge(ids);
      toast.success(`Purged original files for ${ids.length} books`);
      setSelected(new Set());
      setVerifications(new Map());
      refetch();
    } catch {
      toast.error('Failed to purge files');
    } finally {
      setIsPurging(false);
    }
  };

  const verifiedCount = Array.from(selected).filter(
    (id) => verifications.get(id)?.verified,
  ).length;

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
          <h1 className="text-2xl font-bold">Purge Originals</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
            {books?.length || 0} organized books with original files remaining
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => {
              if (books) setSelected(new Set(books.map((b) => b.id)));
            }}
            className="px-3 py-2 rounded text-sm border"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
          >
            Select All
          </button>
          <button
            onClick={handleVerify}
            disabled={selected.size === 0 || isVerifying}
            className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {isVerifying ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <ShieldCheck size={16} />
            )}
            Verify
          </button>
          <button
            onClick={() => setShowConfirm(true)}
            disabled={verifiedCount === 0 || isPurging}
            className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-danger)' }}
          >
            {isPurging ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
            Purge ({verifiedCount})
          </button>
        </div>
      </div>

      {/* Book list */}
      <div className="space-y-2">
        {books?.map((book) => {
          const v = verifications.get(book.id);
          return (
            <div
              key={book.id}
              onClick={() => toggleSelect(book.id)}
              className="flex items-center gap-4 rounded-lg border px-4 py-3 cursor-pointer"
              style={{
                backgroundColor: selected.has(book.id) ? 'var(--color-surface-hover)' : 'var(--color-surface)',
                borderColor: v
                  ? v.verified
                    ? 'var(--color-success)'
                    : 'var(--color-danger)'
                  : 'var(--color-border)',
              }}
            >
              <input
                type="checkbox"
                checked={selected.has(book.id)}
                onChange={() => toggleSelect(book.id)}
              />
              <div className="flex-1 min-w-0">
                <span className="font-medium text-sm">{book.title || 'Unknown Title'}</span>
                <span className="text-xs ml-2" style={{ color: 'var(--color-text-muted)' }}>
                  {book.author}
                </span>
              </div>
              {v && (
                <span
                  className="text-xs px-2 py-0.5 rounded"
                  style={{
                    backgroundColor: v.verified ? '#166534' : '#991b1b',
                    color: v.verified ? '#86efac' : '#fca5a5',
                  }}
                >
                  {v.verified ? 'Verified' : `${v.missing_files.length} issues`}
                </span>
              )}
            </div>
          );
        })}

        {books?.length === 0 && (
          <div
            className="text-center py-12 rounded-lg border"
            style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <p style={{ color: 'var(--color-text-muted)' }}>
              No organized books to purge. Organize books first.
            </p>
          </div>
        )}
      </div>

      {showConfirm && (
        <ConfirmDialog
          title="Confirm Purge"
          message={`This will permanently delete the original files for ${verifiedCount} verified books. This action cannot be undone.`}
          confirmLabel="Delete Original Files"
          confirmColor="var(--color-danger)"
          onConfirm={handlePurge}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
}
