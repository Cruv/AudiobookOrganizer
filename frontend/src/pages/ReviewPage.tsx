import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Check, Edit3, Loader2, Search, CheckCheck, Download } from 'lucide-react';
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

export default function ReviewPage() {
  const [searchParams] = useSearchParams();
  const scanId = searchParams.get('scan_id') ? Number(searchParams.get('scan_id')) : undefined;

  const [sort, setSort] = useState('confidence');
  const { data: books, isLoading } = useBooks({ scan_id: scanId, sort });
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

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={32} className="animate-spin" style={{ color: 'var(--color-primary)' }} />
      </div>
    );
  }

  const confirmedCount = books?.filter((b) => b.is_confirmed).length || 0;
  const totalCount = books?.length || 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Review Books</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
            {confirmedCount} / {totalCount} confirmed
            {scanId && ` (Scan #${scanId})`}
          </p>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="mt-2 rounded border px-2 py-1.5 text-sm outline-none"
            style={{
              backgroundColor: 'var(--color-surface)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text)',
            }}
          >
            <option value="confidence">Confidence (Low first)</option>
            <option value="confidence_desc">Confidence (High first)</option>
            <option value="title">Title (A-Z)</option>
            <option value="author">Author (A-Z)</option>
          </select>
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
            Confirm All High-Confidence
          </button>
        </div>
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
              {/* Metadata */}
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

              {/* Actions */}
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

            {/* Before/After paths */}
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
            className="text-center py-12 rounded-lg border"
            style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
          >
            <p style={{ color: 'var(--color-text-muted)' }}>
              No books found. Start by scanning a directory.
            </p>
          </div>
        )}
      </div>

      {/* Edit modal */}
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

      {/* Search modal */}
      {searchingBook && (
        <SearchModal
          book={searchingBook}
          onClose={() => setSearchingBook(null)}
        />
      )}
    </div>
  );
}
