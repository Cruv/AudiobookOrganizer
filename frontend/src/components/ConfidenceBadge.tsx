interface Props {
  confidence: number;
}

export default function ConfidenceBadge({ confidence }: Props) {
  const pct = Math.round(confidence * 100);
  let bg: string;
  let text: string;

  if (confidence >= 0.8) {
    bg = '#166534';
    text = '#86efac';
  } else if (confidence >= 0.5) {
    bg = '#854d0e';
    text = '#fde047';
  } else {
    bg = '#991b1b';
    text = '#fca5a5';
  }

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ backgroundColor: bg, color: text }}
    >
      {pct}%
    </span>
  );
}
