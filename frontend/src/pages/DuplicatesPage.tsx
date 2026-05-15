import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Check, Trash2 } from 'lucide-react';
import * as api from '@/api/client';
import ConfirmDialog from '@/components/ConfirmDialog';
import { useToast } from '@/components/Toast';
import { Button, Card, EmptyState, PageSkeleton } from '@/components/ui';
import { ConfidenceBadge } from '@/components/ui/Badge';
import type { DuplicateGroup, DuplicateBook } from '@/types';

/**
 * Surfaces books that look like duplicates of each other so the user
 * can pick one to keep and delete the rest. Detection is on-the-fly
 * from /api/stats/duplicates — no extra DB tables needed.
 *
 * "Delete" here removes the Book row + its ScannedFolder; files on
 * disk are NOT touched (same semantics as the per-row Remove flow on
 * ReviewPage and PurgePage).
 */
export default function DuplicatesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({
    queryKey: ['duplicates'],
    queryFn: api.getDuplicates,
  });

  // Per-group: which book id the user has picked to keep.
  const [keepByGroup, setKeepByGroup] = useState<Record<string, number>>({});
  const [resolveTarget, setResolveTarget] = useState<{
    group: DuplicateGroup;
    keep: number;
    deleteIds: number[];
  } | null>(null);

  if (isLoading || !data) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-6">Duplicates</h1>
        <PageSkeleton />
      </div>
    );
  }

  const resolve = async () => {
    if (!resolveTarget) return;
    const { group, keep, deleteIds } = resolveTarget;
    setResolveTarget(null);
    try {
      const resp = await api.resolveDuplicates(keep, deleteIds);
      toast.success(`Removed ${resp.deleted} duplicate entr${resp.deleted === 1 ? 'y' : 'ies'}`);
      setKeepByGroup((m) => {
        const next = { ...m };
        delete next[group.key];
        return next;
      });
      qc.invalidateQueries({ queryKey: ['duplicates'] });
      qc.invalidateQueries({ queryKey: ['books'] });
      qc.invalidateQueries({ queryKey: ['stats'] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Resolve failed');
    }
  };

  const groups = data.groups;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Duplicates</h1>
        <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
          {groups.length === 0
            ? 'No duplicates detected.'
            : `${groups.length} group${groups.length === 1 ? '' : 's'} with possible duplicates. Pick the one to keep, then remove the rest. Files on disk are NOT touched — only the database entries.`}
        </p>
      </div>

      {groups.length === 0 ? (
        <EmptyState
          icon={Copy}
          title="No duplicates"
          description="Each book in your library has a unique title + author + edition."
        />
      ) : (
        <div className="space-y-4">
          {groups.map((group) => {
            const initialKeep = keepByGroup[group.key] ?? group.books[0].id;
            const keepId = initialKeep;
            return (
              <Card
                key={group.key}
                header={
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold truncate">
                        {group.title || 'Unknown title'}
                      </h3>
                      <p
                        className="text-xs truncate"
                        style={{ color: 'var(--color-text-muted)' }}
                      >
                        {group.author || 'Unknown author'}
                        {group.edition && (
                          <> &middot; {group.edition}</>
                        )}
                        {' · '}
                        {group.books.length} copies
                      </p>
                    </div>
                    <Button
                      variant="danger"
                      size="sm"
                      icon={<Trash2 size={14} />}
                      disabled={group.books.length < 2}
                      onClick={() =>
                        setResolveTarget({
                          group,
                          keep: keepId,
                          deleteIds: group.books
                            .map((b) => b.id)
                            .filter((id) => id !== keepId),
                        })
                      }
                    >
                      Remove {group.books.length - 1} other{group.books.length - 1 === 1 ? '' : 's'}
                    </Button>
                  </div>
                }
              >
                <ul className="space-y-2">
                  {group.books.map((b) => (
                    <DuplicateRow
                      key={b.id}
                      book={b}
                      isKept={b.id === keepId}
                      onPickKeep={() =>
                        setKeepByGroup((m) => ({ ...m, [group.key]: b.id }))
                      }
                    />
                  ))}
                </ul>
              </Card>
            );
          })}
        </div>
      )}

      {resolveTarget && (
        <ConfirmDialog
          title="Remove duplicate entries?"
          message={`This removes ${resolveTarget.deleteIds.length} database entr${
            resolveTarget.deleteIds.length === 1 ? 'y' : 'ies'
          } and keeps the one you selected. Files on disk are NOT touched — both originals and any organized copies stay exactly where they are.`}
          confirmLabel="Remove Duplicates"
          confirmColor="var(--color-danger)"
          onConfirm={resolve}
          onCancel={() => setResolveTarget(null)}
        />
      )}
    </div>
  );
}

function DuplicateRow({
  book,
  isKept,
  onPickKeep,
}: {
  book: DuplicateBook;
  isKept: boolean;
  onPickKeep: () => void;
}) {
  return (
    <li
      className="flex items-center gap-3 p-2 rounded border cursor-pointer transition-colors"
      style={{
        borderColor: isKept ? 'var(--color-success)' : 'var(--color-border)',
        backgroundColor: isKept ? 'rgba(34,197,94,0.06)' : undefined,
      }}
      onClick={onPickKeep}
    >
      <input
        type="radio"
        name={`keep-${book.id}`}
        checked={isKept}
        onChange={onPickKeep}
        onClick={(e) => e.stopPropagation()}
        aria-label={`Keep ${book.title}`}
      />
      {(book.cover_url || book.organize_status === 'copied') && (
        <img
          src={
            book.organize_status === 'copied'
              ? `/api/books/${book.id}/cover`
              : book.cover_url || ''
          }
          alt=""
          loading="lazy"
          className="w-9 h-12 object-cover rounded flex-shrink-0"
          style={{ backgroundColor: 'var(--color-surface-hover)' }}
          onError={(e) => {
            const img = e.currentTarget;
            if (
              book.organize_status === 'copied' &&
              book.cover_url &&
              img.src.endsWith(`/api/books/${book.id}/cover`)
            ) {
              img.src = book.cover_url;
            } else {
              img.style.display = 'none';
            }
          }}
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium truncate">{book.title || 'Unknown'}</span>
          <ConfidenceBadge confidence={book.confidence} />
          {book.is_confirmed && (
            <span
              className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded"
              style={{ background: 'var(--color-success)', color: 'white' }}
            >
              <Check size={10} /> Confirmed
            </span>
          )}
        </div>
        {book.folder_path && (
          <p
            className="text-xs font-mono mt-0.5 truncate"
            style={{ color: 'var(--color-text-muted)' }}
            title={book.folder_path}
          >
            {book.folder_path}
          </p>
        )}
      </div>
    </li>
  );
}
