import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Check,
  X,
  Edit3,
  Search,
  CheckCheck,
  XCircle,
  Download,
  FolderSearch,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import {
  useBooks,
  useConfirmBook,
  useConfirmBatch,
  useUnconfirmBook,
  useUnconfirmBatch,
  useUpdateBook,
} from '@/hooks/useBooks';
import { exportBooks } from '@/api/client';
import { ConfidenceBadge, SourceBadge, EditionBadge } from '@/components/ui/Badge';
import BookEditModal from '@/components/BookEditModal';
import SearchModal from '@/components/SearchModal';
import { useToast } from '@/components/Toast';
import { Button, Card, Input, Select, EmptyState, PageSkeleton } from '@/components/ui';
import type { Book } from '@/types';

const PAGE_SIZE = 50;

const SORT_OPTIONS = [
  { value: 'confidence', label: 'Confidence (Low first)' },
  { value: 'confidence_desc', label: 'Confidence (High first)' },
  { value: 'title', label: 'Title (A-Z)' },
  { value: 'author', label: 'Author (A-Z)' },
];

const CONFIDENCE_OPTIONS = [
  { value: '', label: 'All Confidence' },
  { value: 'high', label: 'High (80%+)' },
  { value: 'medium', label: 'Medium (50-80%)' },
  { value: 'low', label: 'Low (<50%)' },
];

const EDITION_OPTIONS = [
  { value: '', label: 'All Editions' },
  { value: 'Graphic Audio', label: 'Graphic Audio' },
  { value: 'standard', label: 'Standard' },
];

const STATUS_OPTIONS = [
  { value: '', label: 'All Status' },
  { value: 'true', label: 'Confirmed' },
  { value: 'false', label: 'Unconfirmed' },
];

export default function ReviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const scanId = searchParams.get('scan_id') ? Number(searchParams.get('scan_id')) : undefined;

  const [sort, setSort] = useState(searchParams.get('sort') || 'confidence');
  const [page, setPage] = useState(Number(searchParams.get('page')) || 1);
  const [searchInput, setSearchInput] = useState(searchParams.get('search') || '');
  const [debouncedSearch, setDebouncedSearch] = useState(searchParams.get('search') || '');
  const [filterEdition, setFilterEdition] = useState(searchParams.get('edition') || '');
  const [filterConfirmed, setFilterConfirmed] = useState(searchParams.get('confirmed') || '');
  const [filterConfidence, setFilterConfidence] = useState(searchParams.get('confidence') || '');

  // Sync state to URL params
  useEffect(() => {
    const params = new URLSearchParams();
    if (scanId) params.set('scan_id', String(scanId));
    if (sort && sort !== 'confidence') params.set('sort', sort);
    if (page > 1) params.set('page', String(page));
    if (debouncedSearch) params.set('search', debouncedSearch);
    if (filterEdition) params.set('edition', filterEdition);
    if (filterConfirmed) params.set('confirmed', filterConfirmed);
    if (filterConfidence) params.set('confidence', filterConfidence);
    setSearchParams(params, { replace: true });
  }, [scanId, sort, page, debouncedSearch, filterEdition, filterConfirmed, filterConfidence, setSearchParams]);

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Reset page on filter change
  const resetPage = useCallback(() => setPage(1), []);
  useEffect(() => { resetPage(); }, [debouncedSearch, filterEdition, filterConfirmed, filterConfidence, sort, resetPage]);

  const { data: booksData, isLoading } = useBooks({
    scan_id: scanId,
    sort,
    page,
    page_size: PAGE_SIZE,
    search: debouncedSearch || undefined,
    edition: filterEdition || undefined,
    confirmed: filterConfirmed === '' ? undefined : filterConfirmed === 'true',
    min_confidence: filterConfidence === 'high' ? 0.8 : filterConfidence === 'medium' ? 0.5 : filterConfidence === 'low' ? 0 : undefined,
    max_confidence: filterConfidence === 'low' ? 0.5 : filterConfidence === 'medium' ? 0.8 : undefined,
  });
  const books = booksData?.items;
  const totalPages = booksData?.total_pages || 1;
  const totalCount = booksData?.total || 0;

  const confirmBook = useConfirmBook();
  const confirmBatch = useConfirmBatch();
  const unconfirmBook = useUnconfirmBook();
  const unconfirmBatch = useUnconfirmBatch();
  const updateBook = useUpdateBook();
  const toast = useToast();

  const [editingBook, setEditingBook] = useState<Book | null>(null);
  const [searchingBook, setSearchingBook] = useState<Book | null>(null);

  const handleExport = async () => {
    try {
      const data = await exportBooks(scanId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audiobook-export${scanId ? `-scan${scanId}` : ''}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success('Export downloaded');
    } catch {
      toast.error('Export failed');
    }
  };

  const handleConfirmHighConfidence = () => {
    confirmBatch.mutate(
      { min_confidence: 0.8, scan_id: scanId },
      {
        onSuccess: (data) => toast.success(`Confirmed ${data.confirmed} books`),
        onError: () => toast.error('Failed to confirm books'),
      },
    );
  };

  const handleResetAllConfirmations = () => {
    if (!confirm('Reset all confirmations for this scan?')) return;
    unconfirmBatch.mutate(
      { scan_id: scanId },
      {
        onSuccess: (data) => toast.success(`Unconfirmed ${data.unconfirmed} books`),
        onError: () => toast.error('Failed to reset confirmations'),
      },
    );
  };

  if (isLoading && !books) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-6">Review Books</h1>
        <PageSkeleton />
      </div>
    );
  }

  const confirmedCount = books?.filter((b) => b.is_confirmed).length || 0;
  const hasFilters = !!(debouncedSearch || filterEdition || filterConfirmed || filterConfidence);

  return (
    <div>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-bold">Review Books</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
            {totalCount} books{confirmedCount > 0 && ` (${confirmedCount} confirmed on this page)`}
            {scanId && ` \u00b7 Scan #${scanId}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<Download size={14} />}
            onClick={handleExport}
            title="Export matching diagnostics as JSON"
          >
            Export
          </Button>
          <Button
            variant="success"
            size="sm"
            icon={<CheckCheck size={14} />}
            loading={confirmBatch.isPending}
            onClick={handleConfirmHighConfidence}
          >
            Confirm High
          </Button>
          <Button
            variant="danger"
            size="sm"
            icon={<XCircle size={14} />}
            loading={unconfirmBatch.isPending}
            onClick={handleResetAllConfirmations}
          >
            Reset All
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <Card className="mb-4">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <div className="sm:col-span-2 lg:col-span-1">
            <Input
              label="Search"
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Title or author..."
            />
          </div>
          <Select
            label="Sort"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            options={SORT_OPTIONS}
          />
          <Select
            label="Confidence"
            value={filterConfidence}
            onChange={(e) => setFilterConfidence(e.target.value)}
            options={CONFIDENCE_OPTIONS}
          />
          <Select
            label="Edition"
            value={filterEdition}
            onChange={(e) => setFilterEdition(e.target.value)}
            options={EDITION_OPTIONS}
          />
          <Select
            label="Status"
            value={filterConfirmed}
            onChange={(e) => setFilterConfirmed(e.target.value)}
            options={STATUS_OPTIONS}
          />
        </div>
      </Card>

      {/* Book list */}
      <div className="space-y-2">
        {books?.map((book) => (
          <Card
            key={book.id}
            borderColor={book.is_confirmed ? 'var(--color-success)' : undefined}
            borderWidth={book.is_confirmed ? '2px' : undefined}
          >
            <div className="flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <span className="font-medium text-sm truncate">
                    {book.title || 'Unknown Title'}
                  </span>
                  <ConfidenceBadge confidence={book.confidence} />
                  <SourceBadge source={book.source} />
                  {book.edition && <EditionBadge edition={book.edition} />}
                </div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  <span>{book.author || 'Unknown Author'}</span>
                  {book.series && (
                    <span>
                      {book.series}
                      {book.series_position && ` #${book.series_position}`}
                    </span>
                  )}
                  {book.year && <span>{book.year}</span>}
                  {book.narrator && <span>Narrated by {book.narrator}</span>}
                </div>
              </div>

              <div className="flex items-center gap-1 flex-shrink-0">
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Search size={15} />}
                  onClick={() => setSearchingBook(book)}
                  title="Search Online"
                  aria-label="Search online"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Edit3 size={15} />}
                  onClick={() => setEditingBook(book)}
                  title="Edit"
                  aria-label="Edit metadata"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  icon={book.is_confirmed ? <X size={15} /> : <Check size={15} />}
                  onClick={() =>
                    book.is_confirmed
                      ? unconfirmBook.mutate(book.id, {
                          onSuccess: () => toast.success('Book unconfirmed'),
                        })
                      : confirmBook.mutate(book.id, {
                          onSuccess: () => toast.success('Book confirmed'),
                        })
                  }
                  title={book.is_confirmed ? 'Unconfirm' : 'Confirm'}
                  aria-label={book.is_confirmed ? 'Unconfirm book' : 'Confirm book'}
                  style={{ color: book.is_confirmed ? 'var(--color-success)' : undefined }}
                />
              </div>
            </div>

            <div className="mt-2 text-xs font-mono space-y-0.5">
              <div className="flex gap-2 truncate">
                <span className="flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>Source:</span>
                <span className="truncate" style={{ color: 'var(--color-text-muted)', opacity: 0.7 }}>
                  {book.folder_path || book.folder_name || '\u2014'}
                </span>
              </div>
              <div className="flex gap-2 truncate">
                <span className="flex-shrink-0" style={{ color: 'var(--color-text-muted)' }}>Output:</span>
                <span className="truncate" style={{ color: 'var(--color-success)' }}>
                  {book.projected_path || '\u2014'}
                </span>
              </div>
            </div>
          </Card>
        ))}

        {books?.length === 0 && (
          <EmptyState
            icon={FolderSearch}
            title={hasFilters ? 'No books match your filters' : 'No books found'}
            description={
              hasFilters
                ? 'Try adjusting your search or filter criteria.'
                : 'Start by scanning a directory on the Scan page.'
            }
          />
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-4 mt-6">
          <Button
            variant="secondary"
            size="sm"
            icon={<ChevronLeft size={16} />}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            Previous
          </Button>
          <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Page {page} of {totalPages}
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
          >
            Next
            <ChevronRight size={16} />
          </Button>
        </div>
      )}

      {editingBook && (
        <BookEditModal
          book={editingBook}
          onSave={(data) => {
            updateBook.mutate(
              { id: editingBook.id, data },
              {
                onSuccess: () => {
                  toast.success('Metadata saved');
                  setEditingBook(null);
                },
                onError: () => toast.error('Failed to save metadata'),
              },
            );
          }}
          onClose={() => setEditingBook(null)}
        />
      )}

      {searchingBook && (
        <SearchModal
          book={searchingBook}
          onClose={() => setSearchingBook(null)}
        />
      )}
    </div>
  );
}
