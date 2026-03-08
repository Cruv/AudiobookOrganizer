import type { LookupResult } from '@/types';

interface Props {
  results: LookupResult[];
  onApply: (provider: string, index: number) => void;
  onClose: () => void;
}

export default function LookupResults({ results, onApply, onClose }: Props) {
  if (results.length === 0) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
        <div
          className="w-full max-w-md rounded-lg border p-6 text-center"
          style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          <p className="mb-4" style={{ color: 'var(--color-text-muted)' }}>
            No results found.
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded text-sm border"
            style={{ borderColor: 'var(--color-border)' }}
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        className="w-full max-w-2xl rounded-lg border p-6 max-h-[80vh] overflow-auto"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <h2 className="text-lg font-semibold mb-4">Lookup Results</h2>
        <div className="space-y-3">
          {results.map((result, idx) => (
            <div
              key={idx}
              className="flex items-start gap-3 p-3 rounded border cursor-pointer hover:bg-[var(--color-surface-hover)]"
              style={{ borderColor: 'var(--color-border)' }}
              onClick={() => onApply(result.provider, idx)}
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
        <div className="flex justify-end mt-4">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded text-sm border"
            style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
