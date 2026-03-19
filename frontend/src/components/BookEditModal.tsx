import { useState } from 'react';
import type { Book } from '@/types';
import { Modal, Input, Button } from '@/components/ui';

interface Props {
  book: Book;
  onSave: (data: {
    title?: string;
    author?: string;
    series?: string | null;
    series_position?: string | null;
    year?: string | null;
    narrator?: string | null;
    edition?: string | null;
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
  const [edition, setEdition] = useState(book.edition || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      title: title || undefined,
      author: author || undefined,
      series: series || null,
      series_position: seriesPosition || null,
      year: year || null,
      narrator: narrator || null,
      edition: edition || null,
    });
  };

  const fields = [
    { label: 'Title', value: title, set: setTitle },
    { label: 'Author', value: author, set: setAuthor },
    { label: 'Series', value: series, set: setSeries },
    { label: 'Series Position', value: seriesPosition, set: setSeriesPosition },
    { label: 'Year', value: year, set: setYear },
    { label: 'Narrator', value: narrator, set: setNarrator },
    { label: 'Edition', value: edition, set: setEdition },
  ];

  return (
    <Modal
      title="Edit Book Metadata"
      subtitle={book.folder_name || book.folder_path || undefined}
      onClose={onClose}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => handleSubmit({ preventDefault: () => {} } as React.FormEvent)}>
            Save
          </Button>
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-3">
        {fields.map(({ label, value, set }) => (
          <Input
            key={label}
            label={label}
            type="text"
            value={value}
            onChange={(e) => set(e.target.value)}
          />
        ))}
      </form>
    </Modal>
  );
}
