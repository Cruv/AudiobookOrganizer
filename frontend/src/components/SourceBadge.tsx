interface Props {
  source: string;
}

const sourceColors: Record<string, { bg: string; text: string }> = {
  parsed: { bg: '#1e3a5f', text: '#93c5fd' },
  tag: { bg: '#3b0764', text: '#d8b4fe' },
  google_books: { bg: '#14532d', text: '#86efac' },
  openlibrary: { bg: '#713f12', text: '#fde047' },
  manual: { bg: '#4c1d95', text: '#c4b5fd' },
};

export default function SourceBadge({ source }: Props) {
  const colors = sourceColors[source] || sourceColors.parsed;
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
      style={{ backgroundColor: colors.bg, color: colors.text }}
    >
      {source}
    </span>
  );
}
