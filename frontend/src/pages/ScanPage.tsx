import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle, FolderOpen, FolderSearch, Trash2, XCircle, Loader2, Download } from 'lucide-react';
import { useScans, useScan, useCreateScan, useDeleteScan, useReimportLibrary } from '@/hooks/useScans';
import DirectoryBrowser from '@/components/DirectoryBrowser';
import ConfirmDialog from '@/components/ConfirmDialog';
import { useToast } from '@/components/Toast';
import { Button, Card, Input } from '@/components/ui';

export default function ScanPage() {
  const [sourceDir, setSourceDir] = useState('');
  const [activeScanId, setActiveScanId] = useState<number | null>(null);
  const [showBrowser, setShowBrowser] = useState(false);
  const [deletingScanId, setDeletingScanId] = useState<number | null>(null);
  const navigate = useNavigate();
  const toast = useToast();

  const { data: scans } = useScans();
  const { data: activeScan } = useScan(activeScanId);
  const createScan = useCreateScan();
  const reimportLibrary = useReimportLibrary();
  const deleteScan = useDeleteScan();

  const handleStartScan = () => {
    if (!sourceDir.trim()) return;
    createScan.mutate(sourceDir.trim(), {
      onSuccess: (scan) => setActiveScanId(scan.id),
    });
  };

  const handleReimport = () => {
    if (!sourceDir.trim()) return;
    reimportLibrary.mutate(sourceDir.trim(), {
      onSuccess: (scan) => {
        setActiveScanId(scan.id);
        toast.success('Re-import started');
      },
      onError: (e: Error) => toast.error(e.message || 'Re-import failed to start'),
    });
  };

  const isScanning = activeScan?.status === 'running';
  const scanComplete = activeScan?.status === 'completed';
  const scanFailed = activeScan?.status === 'failed';
  const progress = activeScan?.total_folders
    ? (activeScan.processed_folders / activeScan.total_folders) * 100
    : 0;

  // Determine scan phase from status_detail
  const getPhaseLabel = (detail?: string | null) => {
    if (!detail) return null;
    if (detail.startsWith('Discovering')) return 'Discovering folders';
    if (detail.startsWith('Processing')) return 'Processing folders';
    if (detail.startsWith('Grouping')) return 'Grouping multi-part books';
    if (detail.startsWith('Looking up') || detail.startsWith('Auto-lookup')) return 'Looking up metadata';
    return detail;
  };

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-bold mb-6">Scan Directory</h1>

      {/* Scan input */}
      <Card className="mb-6">
        <Input
          label="Source Directory"
          hint="Enter the path to your audiobook directory. The scanner will find all folders containing audio files."
          type="text"
          value={sourceDir}
          onChange={(e) => setSourceDir(e.target.value)}
          placeholder="/path/to/audiobooks"
          disabled={isScanning}
          onKeyDown={(e) => e.key === 'Enter' && handleStartScan()}
        />
        <div className="flex flex-wrap gap-2 mt-3">
          <Button
            variant="secondary"
            icon={<FolderOpen size={16} />}
            onClick={() => setShowBrowser(true)}
            disabled={isScanning}
          >
            Browse
          </Button>
          <Button
            icon={isScanning ? undefined : <FolderSearch size={16} />}
            loading={isScanning}
            onClick={handleStartScan}
            disabled={!sourceDir.trim()}
          >
            {isScanning ? 'Scanning...' : 'Start Scan'}
          </Button>
          <Button
            variant="secondary"
            icon={<Download size={16} />}
            loading={reimportLibrary.isPending}
            onClick={handleReimport}
            disabled={!sourceDir.trim() || isScanning}
            title="Rebuild DB from .audiobook-organizer.json sidecar files in this directory"
          >
            Re-import
          </Button>
        </div>
        <p className="text-xs mt-2" style={{ color: 'var(--color-text-muted)' }}>
          <strong>Re-import</strong> reconstructs the library from sidecar files in an
          already-organized directory &mdash; useful if the database was lost
          or when migrating an existing library.
        </p>

        {showBrowser && (
          <DirectoryBrowser
            initialPath={sourceDir.trim() || '/'}
            onSelect={(path) => {
              setSourceDir(path);
              setShowBrowser(false);
            }}
            onClose={() => setShowBrowser(false)}
          />
        )}
      </Card>

      {/* Active scan progress */}
      {activeScan && (
        <Card className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              {isScanning && <Loader2 size={16} className="animate-spin" style={{ color: 'var(--color-primary)' }} />}
              {scanComplete && <CheckCircle size={16} style={{ color: 'var(--color-success)' }} />}
              {scanFailed && <XCircle size={16} style={{ color: 'var(--color-danger)' }} />}
              <span className="text-sm font-medium">
                {isScanning ? 'Scanning...' : scanComplete ? 'Scan Complete' : 'Scan Failed'}
              </span>
            </div>
            <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {activeScan.processed_folders} / {activeScan.total_folders} folders
            </span>
          </div>

          {/* Progress bar */}
          <div className="w-full rounded-full h-2 mb-2" style={{ backgroundColor: 'var(--color-bg)' }}>
            <div
              className="h-2 rounded-full transition-all duration-500"
              style={{
                width: `${progress}%`,
                backgroundColor: scanFailed ? 'var(--color-danger)' : 'var(--color-primary)',
              }}
            />
          </div>

          {/* Phase label */}
          {isScanning && activeScan.status_detail && (
            <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {getPhaseLabel(activeScan.status_detail)}
            </p>
          )}

          {activeScan.error_message && (
            <p className="text-xs mt-2" style={{ color: 'var(--color-danger)' }}>
              {activeScan.error_message}
            </p>
          )}

          {scanComplete && (
            <Button
              variant="success"
              className="mt-3"
              onClick={() => navigate(`/review?scan_id=${activeScan.id}`)}
            >
              Review {activeScan.total_folders} Books
            </Button>
          )}
        </Card>
      )}

      {/* Scan history */}
      {scans && scans.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Scan History</h2>
          <div className="space-y-2">
            {scans.map((scan) => (
              <Card key={scan.id}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    {scan.status === 'completed' ? (
                      <CheckCircle size={16} className="flex-shrink-0" style={{ color: 'var(--color-success)' }} />
                    ) : scan.status === 'failed' ? (
                      <XCircle size={16} className="flex-shrink-0" style={{ color: 'var(--color-danger)' }} />
                    ) : (
                      <Loader2 size={16} className="flex-shrink-0 animate-spin" style={{ color: 'var(--color-primary)' }} />
                    )}
                    <div className="min-w-0">
                      <p className="text-sm font-medium truncate">{scan.source_dir}</p>
                      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        {scan.total_folders} folders &middot;{' '}
                        {new Date(scan.created_at + 'Z').toLocaleString()}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                    {scan.status === 'completed' && (
                      <Button
                        size="sm"
                        onClick={() => navigate(`/review?scan_id=${scan.id}`)}
                      >
                        Review
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Trash2 size={14} />}
                      onClick={() => setDeletingScanId(scan.id)}
                      aria-label="Delete scan"
                    />
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}

      {deletingScanId !== null && (
        <ConfirmDialog
          title="Delete Scan"
          message="This will permanently delete this scan and all associated book data. This action cannot be undone."
          confirmLabel="Delete Scan"
          confirmColor="var(--color-danger)"
          onConfirm={() => {
            deleteScan.mutate(deletingScanId, {
              onSuccess: () => toast.success('Scan deleted'),
              onError: () => toast.error('Failed to delete scan'),
            });
            setDeletingScanId(null);
          }}
          onCancel={() => setDeletingScanId(null)}
        />
      )}
    </div>
  );
}
