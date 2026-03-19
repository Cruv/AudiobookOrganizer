type BadgeVariant = 'confidence' | 'source' | 'edition' | 'status';

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  color?: { bg: string; text: string };
  className?: string;
}

// Confidence thresholds
export function confidenceColor(value: number): { bg: string; text: string } {
  if (value >= 0.8) return { bg: '#166534', text: '#86efac' };
  if (value >= 0.5) return { bg: '#854d0e', text: '#fde047' };
  return { bg: '#991b1b', text: '#fca5a5' };
}

// Source colors
const sourceColors: Record<string, { bg: string; text: string }> = {
  parsed: { bg: '#1e3a5f', text: '#93c5fd' },
  tag: { bg: '#3b0764', text: '#d8b4fe' },
  google_books: { bg: '#14532d', text: '#86efac' },
  openlibrary: { bg: '#713f12', text: '#fde047' },
  manual: { bg: '#4c1d95', text: '#c4b5fd' },
  audible: { bg: '#92400e', text: '#fbbf24' },
  itunes: { bg: '#831843', text: '#f9a8d4' },
};

export function sourceColor(source: string): { bg: string; text: string } {
  const key = source.replace(/^auto:/, '');
  return sourceColors[key] || sourceColors.parsed;
}

export default function Badge({ children, color, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium whitespace-nowrap ${className}`}
      style={color ? { backgroundColor: color.bg, color: color.text } : undefined}
    >
      {children}
    </span>
  );
}

// Convenience components
export function ConfidenceBadge({ confidence }: { confidence: number }) {
  return (
    <Badge color={confidenceColor(confidence)} className="rounded-full">
      {Math.round(confidence * 100)}%
    </Badge>
  );
}

export function SourceBadge({ source }: { source: string }) {
  return (
    <Badge color={sourceColor(source)}>
      {source.replace(/^auto:/, '')}
    </Badge>
  );
}

export function EditionBadge({ edition }: { edition: string }) {
  return (
    <Badge color={{ bg: '#7c3aed22', text: '#a78bfa' }}>
      {edition}
    </Badge>
  );
}

export function StatusBadge({ connected }: { connected: boolean }) {
  return (
    <Badge color={connected ? { bg: '#16653422', text: '#22c55e' } : { bg: '#dc262622', text: '#ef4444' }}>
      {connected ? 'Connected' : 'Not Connected'}
    </Badge>
  );
}
