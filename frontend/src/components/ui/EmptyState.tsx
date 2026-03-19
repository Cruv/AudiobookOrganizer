import type { LucideIcon } from 'lucide-react';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export default function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div
      className="text-center py-16 rounded-lg border"
      style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      <Icon size={48} className="mx-auto mb-4" style={{ color: 'var(--color-text-muted)', opacity: 0.4 }} />
      <p className="font-medium mb-1" style={{ color: 'var(--color-text-muted)' }}>
        {title}
      </p>
      {description && (
        <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)', opacity: 0.7 }}>
          {description}
        </p>
      )}
      {action}
    </div>
  );
}
