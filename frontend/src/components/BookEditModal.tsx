import { useState } from 'react';
import { X } from 'lucide-react';
import type { Book } from '@/types';

interface Props {
  book: Book;
  onSave: (data: {
    title?: string;
    author?: string;
    series?: string | null;
    series_position?: string | null;
    year?: string | null;
    narrator?: string | null;
  }) => void;
  onClose: () => void;
}

export default function BookEditModal({ book, onSave, onClose }: Props) {
  const [title, setTitle] = useState(book.title || '');
  const [author, setAuthor] = useState(book.author || '');
  const [series, setSeries] = useState(book.series || '');
  const [seriesPosition, setSeriesPosition] = useState(book.series_position || '');
  const [year, setYear] = useState(book.year || '');
  const [narrator, setNarrator] = useState(book.narrator || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      title: title || undefined,
      author: author || undefined,
      series: series || null,
      series_position: seriesPosition || null,
      year: year || null,
      narrator: narrator || null,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        className="w-full max-w-lg rounded-lg border p-6"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Edit Book Metadata</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-[var(--color-surface-hover)]">
            <X size={20} />
          </button>
        </div>

        <p className="text-xs mb-4 truncate" style={{ color: 'var(--color-text-muted)' }}>
          {book.folder_name || book.folder_path}
        </p>

        <form onSubmit={handleSubmit} className="space-y-3">
          {[
            { label: 'Title', value: title, set: setTitle },
            { label: 'Author', value: author, set: setAuthor },
            { label: 'Series', value: series, set: setSeries },
            { label: 'Series Position', value: seriesPosition, set: setSeriesPosition },
            { label: 'Year', value: year, set: setYear },
            { label: 'Narrator', value: narrator, set: setNarrator },
          ].map(({ label, value, set }) => (
            <div key={label}>
              <label className="block text-sm mb-1" style={{ color: 'var(--color-text-muted)' }}>
                {label}
              </label>
              <input
                type="text"
                value={value}
                onChange={(e) => set(e.target.value)}
                className="w-full rounded border px-3 py-2 text-sm outline-none focus:ring-2"
                style={{
                  backgroundColor: 'var(--color-bg)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text)',
                }}
              />
            </div>
          ))}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded text-sm border"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 rounded text-sm font-medium text-white"
              style={{ backgroundColor: 'var(--color-primary)' }}
            >
              Save
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
