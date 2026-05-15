import { useEffect, useRef, useState } from 'react';
import { FolderOutput, Eye, FolderCheck, Undo2, History } from 'lucide-react';
import { useBooks } from '@/hooks/useBooks';
import { useQueryClient } from '@tanstack/react-query';
import * as api from '@/api/client';
import type { OrganizePreviewItem } from '@/types';
import { ConfidenceBadge } from '@/components/ui/Badge';
import ConfirmDialog from '@/components/ConfirmDialog';
import { useToast } from '@/components/Toast';
import { Button, Card, EmptyState, PageSkeleton } from '@/components/ui';

/**
 * The Organize page has two tabs:
 *  - "Pending" (default): confirmed books ready to copy.
 *  - "Recent": already-organized books, ordered newest first, with an
 *    Undo control so the user can reverse a mistaken organize before
 *    purging the originals.
 */
type Tab = 'pending' | 'recent';

export default function OrganizePage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('pending');

  const { data: booksData, isLoading, refetch } = useBooks({
    confirmed: true,
    organize_status: 'pending',
    page_size: 200,
  });
  const books = booksData?.items;
  const { data: organizedData, refetch: refetchOrganized } = useBooks({
    organize_status: 'copied',
    page_size: 200,
    // Most-recent first so the user sees what they just did at the top.
    sort: 'created_at',
  });
  const organizedBooks = organizedData?.items;

  const [previews, setPreviews] = useState<OrganizePreviewItem[]>([]);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isOrganizing, setIsOrganizing] = useState(false);
  const [organizingIds, setOrganizingIds] = useState<number[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [undoTargetIds, setUndoTargetIds] = useState<number[] | null>(null);
  const [isUndoing, setIsUndoing] = useState(false);

  // Poll per-book organize status while a batch is in flight.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!isOrganizing || organizingIds.length === 0) return;

    const checkProgress = async () => {
      try {
        const statuses = await Promise.all(
          organizingIds.map((id) => api.getOrganizeStatus(id).catch(() => null)),
        );
        const stillRunning = statuses.some(
          (s) => s && s.organize_status === 'copying',
        );
        if (!stillRunning) {
          setIsOrganizing(false);
          setOrganizingIds([]);
          setSelected(new Set());
          setPreviews([]);
          refetch();
          refetchOrganized();
        }
      } catch {
        // ignore transient errors; next tick will retry
      }
    };

    checkProgress();
    pollRef.current = setInterval(checkProgress, 2000);
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [isOrganizing, organizingIds, refetch, refetchOrganized]);

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    const list = tab === 'pending' ? books : organizedBooks;
    if (!list) return;
    setSelected(new Set(list.map((b) => b.id)));
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
    try {
      await api.executeOrganize(ids);
      setOrganizingIds(ids);
      setIsOrganizing(true);
    } catch {
      // executeOrganize threw; nothing in flight, leave UI as-is.
    }
  };

  const handleUndo = async () => {
    if (!undoTargetIds || undoTargetIds.length === 0) return;
    const ids = undoTargetIds;
    setUndoTargetIds(null);
    setIsUndoing(true);
    try {
      const resp = await api.undoOrganize(ids);
      const ok = resp.results.filter((r) => r.success).length;
      const failed = resp.results.length - ok;
      if (ok > 0) {
        toast.success(
          `Undone ${ok} book${ok === 1 ? '' : 's'}; files removed and books back to pending.`,
        );
      }
      if (failed > 0) {
        const reason = resp.results.find((r) => !r.success)?.error;
        toast.error(`Couldn't undo ${failed}${reason ? `: ${reason}` : ''}.`);
      }
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ['books'] });
    } catch {
      toast.error('Undo failed');
    } finally {
      setIsUndoing(false);
    }
  };

  if (isLoading) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-6">Organize</h1>
        <PageSkeleton />
      </div>
    );
  }

  const activeList = tab === 'pending' ? books : organizedBooks;
  const selectedInTab = Array.from(selected).filter((id) =>
    activeList?.some((b) => b.id === id),
  );

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-bold">Organize</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
            {books?.length || 0} confirmed books ready to organize
            {organizedBooks && organizedBooks.length > 0 && (
              <> &middot; {organizedBooks.length} already organized</>
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={selectAll}>
            Select All
          </Button>
          {tab === 'pending' ? (
            <>
              <Button
                size="sm"
                icon={<Eye size={14} />}
                loading={isPreviewing}
                disabled={selectedInTab.length === 0}
                onClick={handlePreview}
              >
                Preview
              </Button>
              <Button
                variant="success"
                size="sm"
                icon={<FolderOutput size={14} />}
                loading={isOrganizing}
                disabled={selectedInTab.length === 0}
                onClick={handleOrganize}
              >
                Organize ({selectedInTab.length})
              </Button>
            </>
          ) : (
            <Button
              variant="danger"
              size="sm"
              icon={<Undo2 size={14} />}
              loading={isUndoing}
              disabled={selectedInTab.length === 0}
              onClick={() => setUndoTargetIds(selectedInTab)}
              title="Delete the copied files and reset books to pending. Originals are untouched."
            >
              Undo ({selectedInTab.length})
            </Button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
        <button
          type="button"
          onClick={() => {
            setTab('pending');
            setSelected(new Set());
          }}
          className="px-3 py-2 text-sm border-b-2 transition-colors"
          style={{
            borderColor: tab === 'pending' ? 'var(--color-primary)' : 'transparent',
            color: tab === 'pending' ? 'var(--color-text)' : 'var(--color-text-muted)',
          }}
        >
          <FolderOutput size={14} className="inline mr-1.5 align-middle" />
          Pending ({books?.length || 0})
        </button>
        <button
          type="button"
          onClick={() => {
            setTab('recent');
            setSelected(new Set());
          }}
          className="px-3 py-2 text-sm border-b-2 transition-colors"
          style={{
            borderColor: tab === 'recent' ? 'var(--color-primary)' : 'transparent',
            color: tab === 'recent' ? 'var(--color-text)' : 'var(--color-text-muted)',
          }}
        >
          <History size={14} className="inline mr-1.5 align-middle" />
          Recently organized ({organizedBooks?.length || 0})
        </button>
      </div>

      {/* Preview results */}
      {tab === 'pending' && previews.length > 0 && (
        <Card className="mb-6" header={<h3 className="text-sm font-semibold">Path Preview</h3>}>
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
        </Card>
      )}

      {/* Book list */}
      <div className="space-y-2">
        {activeList?.map((book) => (
          <Card
            key={book.id}
            className="cursor-pointer"
            borderColor={selected.has(book.id) ? 'var(--color-primary)' : undefined}
          >
            <div
              className="flex items-center gap-4"
              onClick={() => toggleSelect(book.id)}
            >
              <input
                type="checkbox"
                checked={selected.has(book.id)}
                onChange={() => toggleSelect(book.id)}
                onClick={(e) => e.stopPropagation()}
                className="flex-shrink-0"
                aria-label={`Select ${book.title}`}
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm truncate">{book.title || 'Unknown Title'}</span>
                  <ConfidenceBadge confidence={book.confidence} />
                </div>
                <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  {book.author || 'Unknown Author'}
                </span>
                {tab === 'recent' && book.output_path && (
                  <p
                    className="text-xs font-mono mt-1 truncate"
                    style={{ color: 'var(--color-success)' }}
                    title={book.output_path}
                  >
                    {book.output_path}
                  </p>
                )}
              </div>
            </div>
          </Card>
        ))}

        {tab === 'pending' && books?.length === 0 && (
          <EmptyState
            icon={FolderCheck}
            title="No confirmed books to organize"
            description="Go to the Review page to confirm books first."
          />
        )}
        {tab === 'recent' && organizedBooks?.length === 0 && (
          <EmptyState
            icon={History}
            title="Nothing organized yet"
            description="Books you organize will appear here so you can review or undo recent changes."
          />
        )}
      </div>

      {undoTargetIds && undoTargetIds.length > 0 && (
        <ConfirmDialog
          title={`Undo organize for ${undoTargetIds.length} book${undoTargetIds.length === 1 ? '' : 's'}?`}
          message={
            'This deletes the copied files from the output folder and resets the books to "pending". ' +
            'Original source files are NOT touched. If any source file is missing the undo will be ' +
            'refused for that book (we never delete the only remaining copy of your audio).'
          }
          confirmLabel="Undo Organize"
          confirmColor="var(--color-danger)"
          onConfirm={handleUndo}
          onCancel={() => setUndoTargetIds(null)}
        />
      )}
    </div>
  );
}
