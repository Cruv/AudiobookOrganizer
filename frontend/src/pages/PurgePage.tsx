import { useState } from 'react';
import { ShieldCheck, Trash2, FolderOutput, CheckCircle, AlertTriangle } from 'lucide-react';
import { useBooks } from '@/hooks/useBooks';
import * as api from '@/api/client';
import ConfirmDialog from '@/components/ConfirmDialog';
import { useToast } from '@/components/Toast';
import { Button, Card, EmptyState, PageSkeleton } from '@/components/ui';
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
      <div>
        <h1 className="text-2xl font-bold mb-6">Purge Originals</h1>
        <PageSkeleton />
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold">Purge Originals</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
            {books?.length || 0} organized books with original files remaining
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              if (books) setSelected(new Set(books.map((b) => b.id)));
            }}
          >
            Select All
          </Button>
          <Button
            size="sm"
            icon={<ShieldCheck size={14} />}
            loading={isVerifying}
            disabled={selected.size === 0}
            onClick={handleVerify}
          >
            Verify
          </Button>
          <Button
            variant="danger"
            size="sm"
            icon={<Trash2 size={14} />}
            loading={isPurging}
            disabled={verifiedCount === 0}
            onClick={() => setShowConfirm(true)}
          >
            Purge ({verifiedCount})
          </Button>
        </div>
      </div>

      {/* Workflow hint */}
      {books && books.length > 0 && verifications.size === 0 && (
        <Card className="mb-4">
          <div className="flex items-center gap-3 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            <ShieldCheck size={18} style={{ color: 'var(--color-primary)' }} />
            <div>
              <p className="font-medium" style={{ color: 'var(--color-text)' }}>Step 1: Select and Verify</p>
              <p className="text-xs">Select books, then click Verify to check that all files were copied correctly before deleting originals.</p>
            </div>
          </div>
        </Card>
      )}

      {/* Book list */}
      <div className="space-y-2">
        {books?.map((book) => {
          const v = verifications.get(book.id);
          return (
            <Card
              key={book.id}
              className="cursor-pointer"
              borderColor={
                v
                  ? v.verified
                    ? 'var(--color-success)'
                    : 'var(--color-danger)'
                  : selected.has(book.id)
                  ? 'var(--color-primary)'
                  : undefined
              }
            >
              <div
                className="flex items-center gap-4"
                onClick={() => toggleSelect(book.id)}
              >
                <input
                  type="checkbox"
                  checked={selected.has(book.id)}
                  onChange={() => toggleSelect(book.id)}
                  aria-label={`Select ${book.title}`}
                />
                <div className="flex-1 min-w-0">
                  <span className="font-medium text-sm">{book.title || 'Unknown Title'}</span>
                  <span className="text-xs ml-2" style={{ color: 'var(--color-text-muted)' }}>
                    {book.author}
                  </span>
                </div>
                {v && (
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {v.verified ? (
                      <CheckCircle size={14} style={{ color: 'var(--color-success)' }} />
                    ) : (
                      <AlertTriangle size={14} style={{ color: 'var(--color-danger)' }} />
                    )}
                    <span
                      className="text-xs px-2 py-0.5 rounded"
                      style={{
                        backgroundColor: v.verified ? '#166534' : '#991b1b',
                        color: v.verified ? '#86efac' : '#fca5a5',
                      }}
                    >
                      {v.verified ? 'Verified' : `${v.missing_files.length} issues`}
                    </span>
                  </div>
                )}
              </div>
            </Card>
          );
        })}

        {books?.length === 0 && (
          <EmptyState
            icon={FolderOutput}
            title="No organized books to purge"
            description="Organize books first, then come back to purge the originals."
          />
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
