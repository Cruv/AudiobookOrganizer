import { Check, Loader2, RefreshCw, X } from 'lucide-react';
import type { Book, LookupCandidate } from '@/types';
import {
  useCandidates,
  useRelookupBook,
  useApplyCandidate,
  useRejectCandidate,
} from '@/hooks/useBooks';
import { useToast } from '@/components/Toast';
import { Modal, Button } from '@/components/ui';
import { SourceBadge } from '@/components/ui/Badge';

interface Props {
  book: Book;
  onClose: () => void;
}

/**
 * Shows the persisted LookupCandidate rows for a book. Each row shows
 * the candidate's fields, its provider, and a per-field match breakdown
 * so the user can see exactly why the score came out the way it did.
 *
 * Apply = copy this candidate onto the book. Reject = mark it so
 * relookup won't resurrect it. Re-lookup = refresh candidates from
 * providers now (without re-scanning files).
 */
export default function CandidatesModal({ book, onClose }: Props) {
  const { data: candidates, isLoading } = useCandidates(book.id, true);
  const relookup = useRelookupBook();
  const applyCand = useApplyCandidate();
  const rejectCand = useRejectCandidate();
  const toast = useToast();

  const handleRelookup = () => {
    relookup.mutate(
      { id: book.id, autoApply: false },
      {
        onSuccess: (results) =>
          toast.success(`Refreshed ${results.length} candidates`),
        onError: (e: Error) => toast.error(e.message || 'Re-lookup failed'),
      },
    );
  };

  const handleApply = (candidate: LookupCandidate) => {
    applyCand.mutate(
      { bookId: book.id, candidateId: candidate.id },
      {
        onSuccess: () => toast.success(`Applied ${candidate.provider}`),
        onError: () => toast.error('Failed to apply candidate'),
      },
    );
  };

  const handleReject = (candidate: LookupCandidate) => {
    rejectCand.mutate(
      { bookId: book.id, candidateId: candidate.id },
      {
        onSuccess: () => toast.success('Candidate rejected'),
        onError: () => toast.error('Failed to reject'),
      },
    );
  };

  return (
    <Modal
      title="Lookup Candidates"
      subtitle={book.title || book.folder_name || undefined}
      onClose={onClose}
      maxWidth="max-w-3xl"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
          Parse score{' '}
          <span style={{ color: 'var(--color-text)' }}>
            {(book.parse_confidence * 100).toFixed(0)}%
          </span>
          {' · '}
          Applied match{' '}
          <span style={{ color: 'var(--color-text)' }}>
            {(book.match_confidence * 100).toFixed(0)}%
          </span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw size={14} />}
          loading={relookup.isPending}
          onClick={handleRelookup}
          title="Re-run lookup for this book"
        >
          Re-lookup
        </Button>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-8">
          <Loader2
            size={24}
            className="animate-spin"
            style={{ color: 'var(--color-text-muted)' }}
          />
        </div>
      )}

      {!isLoading && (!candidates || candidates.length === 0) && (
        <p className="text-sm text-center py-8" style={{ color: 'var(--color-text-muted)' }}>
          No candidates yet. Click <strong>Re-lookup</strong> to fetch matches
          from enabled providers.
        </p>
      )}

      {candidates && candidates.length > 0 && (
        <div className="space-y-2">
          {candidates.map((c) => (
            <CandidateRow
              key={c.id}
              candidate={c}
              onApply={handleApply}
              onReject={handleReject}
              busy={applyCand.isPending || rejectCand.isPending}
            />
          ))}
        </div>
      )}
    </Modal>
  );
}

interface RowProps {
  candidate: LookupCandidate;
  onApply: (c: LookupCandidate) => void;
  onReject: (c: LookupCandidate) => void;
  busy: boolean;
}

function CandidateRow({ candidate, onApply, onReject, busy }: RowProps) {
  const border = candidate.applied
    ? 'var(--color-success)'
    : candidate.rejected
      ? 'var(--color-danger)'
      : 'var(--color-border)';
  const opacity = candidate.rejected ? 0.5 : 1;

  return (
    <div
      className="flex items-start gap-3 p-3 rounded border"
      style={{ borderColor: border, opacity, borderWidth: candidate.applied ? '2px' : '1px' }}
    >
      {candidate.cover_url && (
        <img
          src={candidate.cover_url}
          alt=""
          className="w-12 h-16 object-cover rounded flex-shrink-0"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <p className="font-medium text-sm truncate">
            {candidate.title || 'Unknown Title'}
          </p>
          <SourceBadge source={candidate.provider} />
          {candidate.applied && (
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{
                background: 'var(--color-success)',
                color: 'white',
              }}
            >
              Applied
            </span>
          )}
          {candidate.rejected && (
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{
                background: 'var(--color-danger)',
                color: 'white',
              }}
            >
              Rejected
            </span>
          )}
        </div>

        <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
          {candidate.author || 'Unknown Author'}
          {candidate.year && ` (${candidate.year})`}
        </p>
        {candidate.series && (
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Series: {candidate.series}
            {candidate.series_position && ` #${candidate.series_position}`}
          </p>
        )}
        {candidate.narrator && (
          <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Narrator: {candidate.narrator}
          </p>
        )}

        {/* Score breakdown */}
        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-xs" style={{ color: 'var(--color-text-muted)' }}>
          <span title={`match × trust = ${candidate.match_score.toFixed(2)} × ${candidate.trust_weight.toFixed(2)}`}>
            Ranking: <strong style={{ color: 'var(--color-text)' }}>{(candidate.ranking_score * 100).toFixed(0)}%</strong>
          </span>
          {candidate.match_breakdown && (
            <>
              {[
                ['title', candidate.match_breakdown.title],
                ['author', candidate.match_breakdown.author],
                ['series', candidate.match_breakdown.series],
                ['year', candidate.match_breakdown.year],
                ['narrator', candidate.match_breakdown.narrator],
              ].map(([name, score]) => {
                if (score == null) return null;
                const pct = (score as number) * 100;
                return (
                  <span key={name as string} title={`${name}: ${pct.toFixed(0)}% similar`}>
                    {name as string} {pct.toFixed(0)}%
                  </span>
                );
              })}
            </>
          )}
        </div>

        {candidate.description && (
          <p className="text-xs mt-1 line-clamp-2" style={{ color: 'var(--color-text-muted)' }}>
            {candidate.description}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1 flex-shrink-0">
        {!candidate.applied && !candidate.rejected && (
          <Button
            variant="success"
            size="sm"
            icon={<Check size={14} />}
            onClick={() => onApply(candidate)}
            disabled={busy}
            aria-label="Apply this candidate"
          >
            Apply
          </Button>
        )}
        {!candidate.rejected && (
          <Button
            variant="ghost"
            size="sm"
            icon={<X size={14} />}
            onClick={() => onReject(candidate)}
            disabled={busy}
            aria-label="Reject this candidate"
          >
            Reject
          </Button>
        )}
      </div>
    </div>
  );
}
