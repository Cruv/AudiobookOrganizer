import { useState } from 'react';
import { Loader2, Search } from 'lucide-react';
import type { Book, LookupResult } from '@/types';
import { useSearchBook, useApplyLookup } from '@/hooks/useBooks';
import { useToast } from '@/components/Toast';
import { Modal, Button, Input } from '@/components/ui';
import { SourceBadge } from '@/components/ui/Badge';

interface Props {
  book: Book;
  onClose: () => void;
}

export default function SearchModal({ book, onClose }: Props) {
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
    <Modal
      title="Search Metadata"
      subtitle={book.folder_name || book.folder_path || undefined}
      onClose={onClose}
      maxWidth="max-w-2xl"
    >
      {/* Search input */}
      <div className="flex gap-2 mb-4">
        <Input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search for book title, author..."
          className="flex-1"
        />
        <Button
          icon={searchBook.isPending ? undefined : <Search size={16} />}
          loading={searchBook.isPending}
          disabled={!query.trim()}
          onClick={handleSearch}
        >
          Search
        </Button>
      </div>

      {/* Results */}
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
              className="flex items-start gap-3 p-3 rounded border cursor-pointer hover:bg-[var(--color-surface-hover)] transition-colors"
              style={{ borderColor: 'var(--color-border)' }}
              onClick={() => handleApply(result.provider, idx)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => e.key === 'Enter' && handleApply(result.provider, idx)}
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
                {result.narrator && (
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    Narrator: {result.narrator}
                  </p>
                )}
                {result.description && (
                  <p className="text-xs mt-1 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
                    {result.description}
                  </p>
                )}
                <div className="mt-1">
                  <SourceBadge source={result.provider} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
