import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FolderOpen, FolderSearch, Loader2, Trash2 } from 'lucide-react';
import { useScans, useScan, useCreateScan, useDeleteScan } from '@/hooks/useScans';
import DirectoryBrowser from '@/components/DirectoryBrowser';

export default function ScanPage() {
  const [sourceDir, setSourceDir] = useState('');
  const [activeScanId, setActiveScanId] = useState<number | null>(null);
  const [showBrowser, setShowBrowser] = useState(false);
  const navigate = useNavigate();

  const { data: scans } = useScans();
  const { data: activeScan } = useScan(activeScanId);
  const createScan = useCreateScan();
  const deleteScan = useDeleteScan();

  const handleStartScan = () => {
    if (!sourceDir.trim()) return;
    createScan.mutate(sourceDir.trim(), {
      onSuccess: (scan) => {
        setActiveScanId(scan.id);
      },
    });
  };

  const isScanning = activeScan?.status === 'running';
  const scanComplete = activeScan?.status === 'completed';

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-bold mb-6">Scan Directory</h1>

      {/* Scan input */}
      <div
        className="rounded-lg border p-6 mb-6"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <label className="block text-sm font-medium mb-2">Source Directory</label>
        <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
          Enter the path to your audiobook directory. The scanner will find all folders
          containing audio files.
        </p>
        <div className="flex gap-3">
          <div className="flex-1 flex gap-2">
            <input
              type="text"
              value={sourceDir}
              onChange={(e) => setSourceDir(e.target.value)}
              placeholder="/path/to/audiobooks"
              disabled={isScanning}
              className="flex-1 rounded border px-3 py-2 text-sm outline-none focus:ring-2 disabled:opacity-50"
              style={{
                backgroundColor: 'var(--color-bg)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text)',
              }}
              onKeyDown={(e) => e.key === 'Enter' && handleStartScan()}
            />
            <button
              onClick={() => setShowBrowser(true)}
              disabled={isScanning}
              className="flex items-center gap-1.5 px-3 py-2 rounded text-sm border disabled:opacity-50"
              style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
              title="Browse directories"
            >
              <FolderOpen size={16} />
              Browse
            </button>
          </div>
          <button
            onClick={handleStartScan}
            disabled={isScanning || !sourceDir.trim()}
            className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {isScanning ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <FolderSearch size={16} />
            )}
            {isScanning ? 'Scanning...' : 'Start Scan'}
          </button>
        </div>

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
      </div>

      {/* Active scan progress */}
      {activeScan && (
        <div
          className="rounded-lg border p-4 mb-6"
          style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">
              {isScanning ? 'Scanning...' : scanComplete ? 'Scan Complete' : 'Scan Failed'}
            </span>
            <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              {activeScan.processed_folders} / {activeScan.total_folders} folders
            </span>
          </div>
          <div className="w-full rounded-full h-2" style={{ backgroundColor: 'var(--color-bg)' }}>
            <div
              className="h-2 rounded-full transition-all duration-300"
              style={{
                width: `${activeScan.total_folders > 0 ? (activeScan.processed_folders / activeScan.total_folders) * 100 : 0}%`,
                backgroundColor: activeScan.status === 'failed' ? 'var(--color-danger)' : 'var(--color-primary)',
              }}
            />
          </div>
          {activeScan.error_message && (
            <p className="text-xs mt-2" style={{ color: 'var(--color-danger)' }}>
              {activeScan.error_message}
            </p>
          )}
          {scanComplete && (
            <button
              onClick={() => navigate(`/review?scan_id=${activeScan.id}`)}
              className="mt-3 px-4 py-2 rounded text-sm font-medium text-white"
              style={{ backgroundColor: 'var(--color-success)' }}
            >
              Review {activeScan.total_folders} Books
            </button>
          )}
        </div>
      )}

      {/* Scan history */}
      {scans && scans.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Scan History</h2>
          <div className="space-y-2">
            {scans.map((scan) => (
              <div
                key={scan.id}
                className="flex items-center justify-between rounded-lg border px-4 py-3"
                style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
              >
                <div>
                  <p className="text-sm font-medium">{scan.source_dir}</p>
                  <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    {scan.total_folders} folders &middot; {scan.status} &middot;{' '}
                    {new Date(scan.created_at).toLocaleString()}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {scan.status === 'completed' && (
                    <button
                      onClick={() => navigate(`/review?scan_id=${scan.id}`)}
                      className="px-3 py-1.5 rounded text-xs font-medium"
                      style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}
                    >
                      Review
                    </button>
                  )}
                  <button
                    onClick={() => deleteScan.mutate(scan.id)}
                    className="p-1.5 rounded hover:bg-[var(--color-surface-hover)]"
                    style={{ color: 'var(--color-text-muted)' }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
