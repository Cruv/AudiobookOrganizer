import { useState } from 'react';
import { Modal, Button, Input, Select } from '@/components/ui';
import { useBulkUpdateBooks } from '@/hooks/useBooks';
import { useToast } from '@/components/Toast';

interface Props {
  bookIds: number[];
  onClose: () => void;
}

/**
 * Apply a metadata patch to multiple books at once.
 *
 * Each field starts blank — only the fields the user fills in are sent.
 * An empty string clears the field on the server (server coerces "" to
 * null). Title is deliberately not bulk-editable: setting the same title
 * across N books is almost always a mistake.
 */
export default function BulkEditModal({ bookIds, onClose }: Props) {
  const [author, setAuthor] = useState('');
  const [series, setSeries] = useState('');
  const [seriesPosition, setSeriesPosition] = useState('');
  const [year, setYear] = useState('');
  const [narrator, setNarrator] = useState('');
  const [edition, setEdition] = useState('');
  const [flags, setFlags] = useState<'none' | 'confirm' | 'lock'>('none');

  const bulkUpdate = useBulkUpdateBooks();
  const toast = useToast();

  const handleApply = () => {
    const patch: Record<string, string | boolean | null> = {};
    if (author) patch.author = author;
    if (series) patch.series = series;
    if (seriesPosition) patch.series_position = seriesPosition;
    if (year) patch.year = year;
    if (narrator) patch.narrator = narrator;
    if (edition) patch.edition = edition;
    if (flags === 'confirm') patch.is_confirmed = true;
    if (flags === 'lock') patch.locked = true;

    if (Object.keys(patch).length === 0) {
      toast.error('Nothing to apply — fill in at least one field');
      return;
    }

    bulkUpdate.mutate(
      { book_ids: bookIds, patch },
      {
        onSuccess: (data) => {
          const changes = Object.entries(data.field_counts)
            .filter(([, n]) => n > 0)
            .map(([f, n]) => `${f}: ${n}`)
            .join(', ');
          toast.success(
            `Updated ${data.updated} book${data.updated === 1 ? '' : 's'}` +
              (changes ? ` (${changes})` : ''),
          );
          onClose();
        },
        onError: (e: Error) => toast.error(e.message || 'Bulk update failed'),
      },
    );
  };

  return (
    <Modal
      title={`Bulk Edit ${bookIds.length} Book${bookIds.length === 1 ? '' : 's'}`}
      subtitle="Only the fields you fill in will be applied. Leave blank to skip."
      onClose={onClose}
      maxWidth="max-w-xl"
    >
      <div className="space-y-3">
        <Input label="Author" value={author} onChange={(e) => setAuthor(e.target.value)} />
        <div className="grid grid-cols-2 gap-3">
          <Input label="Series" value={series} onChange={(e) => setSeries(e.target.value)} />
          <Input
            label="Series Position"
            value={seriesPosition}
            onChange={(e) => setSeriesPosition(e.target.value)}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Input
            label="Year"
            value={year}
            onChange={(e) => setYear(e.target.value)}
            placeholder="YYYY"
          />
          <Input label="Narrator" value={narrator} onChange={(e) => setNarrator(e.target.value)} />
        </div>
        <Input
          label="Edition"
          value={edition}
          onChange={(e) => setEdition(e.target.value)}
          placeholder="e.g. Graphic Audio"
        />

        <div>
          <Select
            label="Also..."
            value={flags}
            onChange={(e) => setFlags(e.target.value as 'none' | 'confirm' | 'lock')}
            options={[
              { value: 'none', label: 'Nothing extra' },
              { value: 'confirm', label: 'Mark as confirmed' },
              { value: 'lock', label: 'Lock (freeze metadata)' },
            ]}
          />
          <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
            Flags applied alongside field edits.
          </p>
        </div>

        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
          <strong>Tip:</strong> leave a field empty to skip it. Fields with
          text will overwrite the current value on all selected books.
        </p>

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={bulkUpdate.isPending} onClick={handleApply}>
            Apply to {bookIds.length}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
