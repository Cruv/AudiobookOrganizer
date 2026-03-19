interface CardProps {
  children: React.ReactNode;
  header?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  borderColor?: string;
  borderWidth?: string;
}

export default function Card({ children, header, footer, className = '', borderColor, borderWidth }: CardProps) {
  return (
    <div
      className={`rounded-lg border ${className}`}
      style={{
        backgroundColor: 'var(--color-surface)',
        borderColor: borderColor || 'var(--color-border)',
        borderWidth: borderWidth || '1px',
      }}
    >
      {header && (
        <div className="px-5 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
          {header}
        </div>
      )}
      <div className="p-5">{children}</div>
      {footer && (
        <div className="px-5 py-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
          {footer}
        </div>
      )}
    </div>
  );
}
