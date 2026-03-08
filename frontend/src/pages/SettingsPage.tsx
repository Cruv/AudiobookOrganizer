import { useEffect, useState } from 'react';
import { Save, RotateCcw } from 'lucide-react';
import { useSettings, useUpdateSettings, usePreviewPattern } from '@/hooks/useSettings';

const PRESETS = {
  chaptarr: '{Author}/{Series}/{SeriesPosition} - {Title} ({Year})',
  audiobookshelf: '{Author}/{Series}/Book {SeriesPosition} - {Year} - {Title} {NarratorBraced}',
};

const TOKENS = [
  '{Author}',
  '{Series}',
  '{SeriesPosition}',
  '{Title}',
  '{Year}',
  '{Narrator}',
  '{NarratorBraced}',
];

export default function SettingsPage() {
  const { data: settings, isLoading } = useSettings();
  const updateSettings = useUpdateSettings();

  const [pattern, setPattern] = useState('');
  const [root, setRoot] = useState('');
  const [apiKey, setApiKey] = useState('');

  const { data: preview } = usePreviewPattern(pattern);

  useEffect(() => {
    if (settings) {
      setPattern(settings.output_pattern);
      setRoot(settings.output_root);
      setApiKey(settings.google_books_api_key || '');
    }
  }, [settings]);

  const handleSave = () => {
    updateSettings.mutate({
      output_pattern: pattern,
      output_root: root,
      google_books_api_key: apiKey || null,
    });
  };

  const insertToken = (token: string) => {
    setPattern((prev) => prev + token);
  };

  if (isLoading) return null;

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="space-y-6">
        {/* Output Root */}
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          <label className="block text-sm font-medium mb-1">Output Root Directory</label>
          <p className="text-xs mb-2" style={{ color: 'var(--color-text-muted)' }}>
            Base directory where organized audiobooks will be placed.
          </p>
          <input
            type="text"
            value={root}
            onChange={(e) => setRoot(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm outline-none"
            style={{
              backgroundColor: 'var(--color-bg)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
        </div>

        {/* Output Pattern */}
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center justify-between mb-1">
            <label className="text-sm font-medium">Output Naming Pattern</label>
            <div className="flex gap-1.5">
              <button
                onClick={() => setPattern(PRESETS.audiobookshelf)}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded"
                style={{ backgroundColor: '#166534', color: '#86efac' }}
              >
                <RotateCcw size={12} />
                Audiobookshelf
              </button>
              <button
                onClick={() => setPattern(PRESETS.chaptarr)}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded"
                style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}
              >
                <RotateCcw size={12} />
                Chaptarr
              </button>
            </div>
          </div>
          <p className="text-xs mb-2" style={{ color: 'var(--color-text-muted)' }}>
            Use tokens to define the folder structure. Segments with missing values are removed.
          </p>
          <input
            type="text"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm font-mono outline-none mb-2"
            style={{
              backgroundColor: 'var(--color-bg)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
          <div className="flex flex-wrap gap-1.5 mb-3">
            {TOKENS.map((token) => (
              <button
                key={token}
                onClick={() => insertToken(token)}
                className="px-2 py-1 rounded text-xs border"
                style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)' }}
              >
                {token}
              </button>
            ))}
          </div>
          {preview && (
            <div className="rounded p-3 text-xs" style={{ backgroundColor: 'var(--color-bg)' }}>
              <span style={{ color: 'var(--color-text-muted)' }}>Preview: </span>
              <span className="font-mono" style={{ color: 'var(--color-success)' }}>
                {root}/{preview.preview}
              </span>
            </div>
          )}
        </div>

        {/* Google Books API Key */}
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          <label className="block text-sm font-medium mb-1">Google Books API Key</label>
          <p className="text-xs mb-2" style={{ color: 'var(--color-text-muted)' }}>
            Optional. Improves online lookup results. Get one at Google Cloud Console.
          </p>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Enter API key..."
            className="w-full rounded border px-3 py-2 text-sm outline-none"
            style={{
              backgroundColor: 'var(--color-bg)',
              borderColor: 'var(--color-border)',
              color: 'var(--color-text)',
            }}
          />
        </div>

        {/* Save */}
        <button
          onClick={handleSave}
          disabled={updateSettings.isPending}
          className="flex items-center gap-2 px-6 py-2.5 rounded text-sm font-medium text-white"
          style={{ backgroundColor: 'var(--color-primary)' }}
        >
          <Save size={16} />
          Save Settings
        </button>
      </div>
    </div>
  );
}
