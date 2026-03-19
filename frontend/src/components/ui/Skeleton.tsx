interface SkeletonProps {
  className?: string;
  count?: number;
}

function SkeletonLine({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded ${className}`}
      style={{ backgroundColor: 'var(--color-surface-hover)' }}
    />
  );
}

export default function Skeleton({ className = 'h-4 w-full', count = 1 }: SkeletonProps) {
  if (count === 1) return <SkeletonLine className={className} />;
  return (
    <div className="space-y-3">
      {Array.from({ length: count }, (_, i) => (
        <SkeletonLine key={i} className={className} />
      ))}
    </div>
  );
}

export function BookCardSkeleton() {
  return (
    <div
      className="rounded-lg border px-4 py-3 space-y-2"
      style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      <div className="flex items-center gap-3">
        <SkeletonLine className="h-4 w-48" />
        <SkeletonLine className="h-5 w-12 rounded-full" />
        <SkeletonLine className="h-5 w-16 rounded" />
      </div>
      <div className="flex gap-4">
        <SkeletonLine className="h-3 w-32" />
        <SkeletonLine className="h-3 w-24" />
      </div>
      <SkeletonLine className="h-3 w-full" />
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 8 }, (_, i) => (
        <BookCardSkeleton key={i} />
      ))}
    </div>
  );
}
