import { useState, useEffect } from 'react';
import { Loader2, Search, X } from 'lucide-react';
import type { Book, LookupResult } from '@/types';
import { useSearchBook, useApplyLookup } from '@/hooks/useBooks';
import { useToast } from '@/components/Toast';

interface Props {
  book: Book;
  onClose: () => void;
}

export default function SearchModal({ book, onClose }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const defaultQuery = [book.title, book.author].filter(Boolean).join(' ');
  const [query, setQuery] = useState(defaultQuery);
  const [results, setResults] = useState<LookupResult[] | null>(null);
  const searchBook = useSearchBook();
  const applyLookup = useApplyLookup();
  const toast = useToast();

  const handleSearch = () => {
    if (!query.trim()) return;
    searchBook.mutate(
      { id: book.id, query: query.trim() },
      {
        onSuccess: (data) => setResults(data.results),
        onError: () => setResults([]),
      },
    );
  };

  const handleApply = (provider: string, index: number) => {
    applyLookup.mutate(
      { id: book.id, data: { provider, result_index: index } },
      {
        onSuccess: () => {
          toast.success('Metadata applied successfully');
          onClose();
        },
        onError: () => toast.error('Failed to apply metadata'),
      },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        className="w-full max-w-2xl rounded-lg border flex flex-col"
        style={{
          backgroundColor: 'var(--color-surface)',
          borderColor: 'var(--color-border)',
          maxHeight: '80vh',
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <div>
            <h2 className="text-lg font-semibold">Search Metadata</h2>
            <p className="text-xs mt-0.5 truncate" style={{ color: 'var(--color-text-muted)' }}>
              {book.folder_name || book.folder_path}
            </p>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--color-surface-hover)]">
            <X size={20} />
          </button>
        </div>

        {/* Search input */}
        <div className="flex gap-2 p-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search for book title, author..."
            className="flex-1 rounded border px-3 py-2 text-sm outline-none focus:ring-2"
            style={{
              backgroundColor: 'var(--color-bg)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
          <button
            onClick={handleSearch}
            disabled={searchBook.isPending || !query.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {searchBook.isPending ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
            Search
          </button>
        </div>

        {/* Results */}
        <div className="flex-1 overflow-y-auto p-4">
          {results === null && !searchBook.isPending && (
            <p className="text-sm text-center py-8" style={{ color: 'var(--color-text-muted)' }}>
              Enter a search query and click Search to find metadata.
            </p>
          )}
          {searchBook.isPending && (
            <div className="flex items-center justify-center py-8">
              <Loader2 size={24} className="animate-spin" style={{ color: 'var(--color-text-muted)' }} />
            </div>
          )}
          {results && results.length === 0 && (
            <p className="text-sm text-center py-8" style={{ color: 'var(--color-text-muted)' }}>
              No results found. Try a different search query.
            </p>
          )}
          {results && results.length > 0 && (
            <div className="space-y-2">
              {results.map((result, idx) => (
                <div
                  key={idx}
                  className="flex items-start gap-3 p-3 rounded border cursor-pointer hover:bg-[var(--color-surface-hover)]"
                  style={{ borderColor: 'var(--color-border)' }}
                  onClick={() => handleApply(result.provider, idx)}
                >
                  {result.cover_url && (
                    <img
                      src={result.cover_url}
                      alt=""
                      className="w-12 h-16 object-cover rounded flex-shrink-0"
                    />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm">{result.title || 'Unknown Title'}</p>
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      {result.author || 'Unknown Author'}
                      {result.year && ` (${result.year})`}
                    </p>
                    {result.series && (
                      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        Series: {result.series}
                        {result.series_position && ` #${result.series_position}`}
                      </p>
                    )}
                    {result.description && (
                      <p className="text-xs mt-1 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
                        {result.description}
                      </p>
                    )}
                    <span
                      className="inline-block mt-1 text-xs px-1.5 py-0.5 rounded"
                      style={{ backgroundColor: 'var(--color-bg)', color: 'var(--color-text-muted)' }}
                    >
                      {result.provider}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
