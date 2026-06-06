import { useState, useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { FolderOutput, Eye, FolderCheck } from 'lucide-react';
import { useBooks } from '@/hooks/useBooks';
import * as api from '@/api/client';
import { useToast } from '@/components/Toast';
import type { OrganizePreviewItem } from '@/types';
import { ConfidenceBadge } from '@/components/ui/Badge';
import { Button, Card, EmptyState, PageSkeleton } from '@/components/ui';

export default function OrganizePage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: booksData, isLoading } = useBooks({
    confirmed: true,
    organize_status: 'pending',
    page_size: 200,
  });
  const books = booksData?.items;
  const { data: organizedData } = useBooks({ organize_status: 'copied', page_size: 200 });
  const organizedBooks = organizedData?.items;

  const [previews, setPreviews] = useState<OrganizePreviewItem[]>([]);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isOrganizing, setIsOrganizing] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Holds the active copy-progress poll so we can stop it on unmount.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(
    () => () => {
      if (pollRef.current !== null) clearInterval(pollRef.current);
    },
    [],
  );

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
    } catch {
      setIsOrganizing(false);
      toast.error('Failed to start organizing');
      return;
    }

    // The submitted books are now 'copying' server-side — drop them from the
    // pending list and clear the selection immediately so they can't be
    // re-selected and re-submitted while the copy runs.
    setSelected(new Set());
    queryClient.invalidateQueries({ queryKey: ['books'] });

    // executeOrganize copies in the background, so poll until none of the
    // submitted books are still 'copying'. We fetch the 'copying' list
    // fresh each tick rather than trusting the render-time `books` (which
    // is filtered to 'pending' and could never show a copying book). Each
    // book lands on 'copied' or 'failed', so this terminates; the tick cap
    // is just a backstop against a crashed copy task.
    const submitted = new Set(ids);
    let ticks = 0;
    const MAX_TICKS = 150; // ~5 min at 2s
    if (pollRef.current !== null) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      ticks += 1;
      let done = ticks >= MAX_TICKS;
      try {
        const copying = await api.getBooks({ organize_status: 'copying', page_size: 200 });
        if (!copying.items.some((b) => submitted.has(b.id))) done = true;
      } catch {
        // transient fetch error — keep polling until the cap
      }
      if (done) {
        if (pollRef.current !== null) clearInterval(pollRef.current);
        pollRef.current = null;
        setIsOrganizing(false);
        setSelected(new Set());
        setPreviews([]);
        queryClient.invalidateQueries({ queryKey: ['books'] });
        toast.success('Organize complete');
      }
    }, 2000);
  };

  if (isLoading) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-6">Organize</h1>
        <PageSkeleton />
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
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
          <Button variant="secondary" size="sm" onClick={selectAll}>
            Select All
          </Button>
          <Button
            size="sm"
            icon={<Eye size={14} />}
            loading={isPreviewing}
            disabled={selected.size === 0}
            onClick={handlePreview}
          >
            Preview
          </Button>
          <Button
            variant="success"
            size="sm"
            icon={<FolderOutput size={14} />}
            loading={isOrganizing}
            disabled={selected.size === 0}
            onClick={handleOrganize}
          >
            Organize ({selected.size})
          </Button>
        </div>
      </div>

      {/* Preview results */}
      {previews.length > 0 && (
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
        {books?.map((book) => (
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
              </div>
            </div>
          </Card>
        ))}

        {books?.length === 0 && (
          <EmptyState
            icon={FolderCheck}
            title="No confirmed books to organize"
            description="Go to the Review page to confirm books first."
          />
        )}
      </div>
    </div>
  );
}
