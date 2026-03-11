import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Check,
  Edit3,
  Loader2,
  Search,
  CheckCheck,
  Download,
  FolderSearch,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import {
  useBooks,
  useConfirmBook,
  useConfirmBatch,
  useUpdateBook,
} from '@/hooks/useBooks';
import { exportBooks } from '@/api/client';
import ConfidenceBadge from '@/components/ConfidenceBadge';
import SourceBadge from '@/components/SourceBadge';
import BookEditModal from '@/components/BookEditModal';
import SearchModal from '@/components/SearchModal';
import { useToast } from '@/components/Toast';
import type { Book } from '@/types';

const PAGE_SIZE = 50;

export default function ReviewPage() {
  const [searchParams] = useSearchParams();
  const scanId = searchParams.get('scan_id') ? Number(searchParams.get('scan_id')) : undefined;

  const [sort, setSort] = useState('confidence');
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [filterEdition, setFilterEdition] = useState('');
  const [filterConfirmed, setFilterConfirmed] = useState('');
  const [filterConfidence, setFilterConfidence] = useState('');

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Reset page when filters change
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

  if (isLoading && !books) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={32} className="animate-spin" style={{ color: 'var(--color-primary)' }} />
      </div>
    );
  }

  const confirmedCount = books?.filter((b) => b.is_confirmed).length || 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold">Review Books</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
            {totalCount} books{confirmedCount > 0 && ` (${confirmedCount} confirmed on this page)`}
            {scanId && ` · Scan #${scanId}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="flex items-center gap-2 px-3 py-2 rounded text-sm font-medium border"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            title="Export matching diagnostics as JSON"
          >
            <Download size={16} />
            Export
          </button>
          <button
            onClick={handleConfirmHighConfidence}
            disabled={confirmBatch.isPending}
            className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium text-white"
            style={{ backgroundColor: 'var(--color-success)' }}
          >
            <CheckCheck size={16} />
            Confirm High
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div
        className="flex flex-wrap items-center gap-3 rounded-lg border px-4 py-3 mb-4"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex-1 min-w-[200px]">
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search title or author..."
            className="w-full rounded border px-3 py-1.5 text-sm outline-none"
            style={{
              backgroundColor: 'var(--color-bg)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="rounded border px-2 py-1.5 text-sm outline-none"
          style={{
            backgroundColor: 'var(--color-bg)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          <option value="confidence">Confidence (Low)</option>
          <option value="confidence_desc">Confidence (High)</option>
          <option value="title">Title (A-Z)</option>
          <option value="author">Author (A-Z)</option>
        </select>
        <select
          value={filterConfidence}
          onChange={(e) => setFilterConfidence(e.target.value)}
          className="rounded border px-2 py-1.5 text-sm outline-none"
          style={{
            backgroundColor: 'var(--color-bg)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          <option value="">All Confidence</option>
          <option value="high">High (80%+)</option>
          <option value="medium">Medium (50-80%)</option>
          <option value="low">Low (&lt;50%)</option>
        </select>
        <select
          value={filterEdition}
          onChange={(e) => setFilterEdition(e.target.value)}
          className="rounded border px-2 py-1.5 text-sm outline-none"
          style={{
            backgroundColor: 'var(--color-bg)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          <option value="">All Editions</option>
          <option value="Graphic Audio">Graphic Audio</option>
          <option value="standard">Standard</option>
        </select>
        <select
          value={filterConfirmed}
          onChange={(e) => setFilterConfirmed(e.target.value)}
          className="rounded border px-2 py-1.5 text-sm outline-none"
          style={{
            backgroundColor: 'var(--color-bg)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          <option value="">All Status</option>
          <option value="true">Confirmed</option>
          <option value="false">Unconfirmed</option>
        </select>
      </div>

      {/* Book list */}
      <div className="space-y-2">
        {books?.map((book) => (
          <div
            key={book.id}
            className="rounded-lg border px-4 py-3"
            style={{
              backgroundColor: 'var(--color-surface)',
              borderColor: book.is_confirmed ? 'var(--color-success)' : 'var(--color-border)',
              borderWidth: book.is_confirmed ? '2px' : '1px',
            }}
          >
            <div className="flex items-center gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm truncate">
                    {book.title || 'Unknown Title'}
                  </span>
                  <ConfidenceBadge confidence={book.confidence} />
                  <SourceBadge source={book.source} />
                  {book.edition && (
                    <span
                      className="px-1.5 py-0.5 rounded text-xs font-medium"
                      style={{ backgroundColor: '#7c3aed22', color: '#7c3aed' }}
                    >
                      {book.edition}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-4 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  <span>{book.author || 'Unknown Author'}</span>
                  {book.series && (
                    <span>
                      {book.series}
                      {book.series_position && ` #${book.series_position}`}
                    </span>
                  )}
                  {book.year && <span>{book.year}</span>}
                </div>
              </div>

              <div className="flex items-center gap-1.5 flex-shrink-0">
                <button
                  onClick={() => setSearchingBook(book)}
                  className="p-2 rounded hover:bg-[var(--color-surface-hover)]"
                  style={{ color: 'var(--color-text-muted)' }}
                  title="Search Online"
                >
                  <Search size={16} />
                </button>
                <button
                  onClick={() => setEditingBook(book)}
                  className="p-2 rounded hover:bg-[var(--color-surface-hover)]"
                  style={{ color: 'var(--color-text-muted)' }}
                  title="Edit"
                >
                  <Edit3 size={16} />
                </button>
                <button
                  onClick={() =>
                    confirmBook.mutate(book.id, {
                      onSuccess: () => toast.success('Book confirmed'),
                    })
                  }
                  disabled={book.is_confirmed}
                  className="p-2 rounded hover:bg-[var(--color-surface-hover)] disabled:opacity-30"
                  style={{ color: book.is_confirmed ? 'var(--color-success)' : 'var(--color-text-muted)' }}
                  title={book.is_confirmed ? 'Confirmed' : 'Confirm'}
                >
                  <Check size={16} />
                </button>
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
          </div>
        ))}

        {books?.length === 0 && (
          <div
            className="text-center py-16 rounded-lg border"
            style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <FolderSearch size={48} className="mx-auto mb-4" style={{ color: 'var(--color-text-muted)', opacity: 0.5 }} />
            <p className="font-medium mb-1" style={{ color: 'var(--color-text-muted)' }}>
              {debouncedSearch || filterEdition || filterConfirmed || filterConfidence
                ? 'No books match your filters'
                : 'No books found'}
            </p>
            <p className="text-sm" style={{ color: 'var(--color-text-muted)', opacity: 0.7 }}>
              {debouncedSearch || filterEdition || filterConfirmed || filterConfidence
                ? 'Try adjusting your search or filter criteria.'
                : 'Start by scanning a directory on the Scan page.'}
            </p>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-4 mt-6">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="flex items-center gap-1 px-3 py-2 rounded text-sm border disabled:opacity-30"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
          >
            <ChevronLeft size={16} />
            Previous
          </button>
          <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="flex items-center gap-1 px-3 py-2 rounded text-sm border disabled:opacity-30"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
          >
            Next
            <ChevronRight size={16} />
          </button>
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
