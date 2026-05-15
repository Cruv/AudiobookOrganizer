import { useQuery } from '@tanstack/react-query';
import { BarChart3, BookCheck, FolderOutput, Lock, Trash2, BookOpen } from 'lucide-react';
import * as api from '@/api/client';
import { Card, EmptyState, PageSkeleton } from '@/components/ui';
import type { CountedItem } from '@/types';

/**
 * Library dashboard — aggregate counts across the whole DB.
 *
 * All numbers come from /api/stats, which does pure GROUP BY/COUNT
 * queries and uses the indexes added in PR 2, so it stays fast at
 * scale. Top-N lists are capped at 25 by the backend.
 */
export default function LibraryPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: api.getStats,
  });

  if (isLoading || !data) {
    return (
      <div>
        <h1 className="text-2xl font-bold mb-6">Library</h1>
        <PageSkeleton />
      </div>
    );
  }

  const { totals, sources, editions, top_authors, top_series, by_decade } = data;
  const hasAny = totals.books > 0;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Library</h1>
        <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
          {totals.books.toLocaleString()} books across your library
        </p>
      </div>

      {!hasAny ? (
        <EmptyState
          icon={BarChart3}
          title="No books yet"
          description="Start a scan to see library statistics here."
        />
      ) : (
        <div className="space-y-6">
          {/* Totals row */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <StatTile label="Books" value={totals.books} icon={BookOpen} />
            <StatTile label="Confirmed" value={totals.confirmed} icon={BookCheck} />
            <StatTile label="Organized" value={totals.organized} icon={FolderOutput} />
            <StatTile label="Purged" value={totals.purged} icon={Trash2} />
            <StatTile label="Locked" value={totals.locked} icon={Lock} />
          </div>

          {/* Breakdown grids */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <BreakdownCard title="By source" items={sources} />
            <BreakdownCard title="By edition" items={editions} />
            <BreakdownCard title="By decade" items={by_decade} />
            <BreakdownCard title="Top authors" items={top_authors} max={15} />
            <BreakdownCard title="Top series" items={top_series} max={15} />
          </div>
        </div>
      )}
    </div>
  );
}

function StatTile({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: typeof BookOpen;
}) {
  return (
    <Card>
      <div className="flex items-center gap-2 mb-1" style={{ color: 'var(--color-text-muted)' }}>
        <Icon size={14} />
        <span className="text-xs uppercase tracking-wider">{label}</span>
      </div>
      <p className="text-2xl font-bold">{value.toLocaleString()}</p>
    </Card>
  );
}

function BreakdownCard({
  title,
  items,
  max = 10,
}: {
  title: string;
  items: CountedItem[];
  max?: number;
}) {
  const top = items.slice(0, max);
  if (top.length === 0) return null;
  const maxCount = Math.max(...top.map((i) => i.count));
  return (
    <Card header={<h3 className="text-sm font-semibold">{title}</h3>}>
      <ul className="space-y-2">
        {top.map((item) => {
          const pct = maxCount > 0 ? (item.count / maxCount) * 100 : 0;
          return (
            <li key={item.name} className="text-xs">
              <div className="flex justify-between mb-0.5">
                <span className="truncate mr-2" title={item.name}>
                  {item.name}
                </span>
                <span
                  className="flex-shrink-0 font-mono"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  {item.count}
                </span>
              </div>
              <div
                className="h-1.5 rounded"
                style={{ backgroundColor: 'var(--color-surface-hover)' }}
              >
                <div
                  className="h-1.5 rounded"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: 'var(--color-primary)',
                  }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
