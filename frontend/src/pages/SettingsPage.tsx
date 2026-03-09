import { useEffect, useState } from 'react';
import { Save, RotateCcw, Link, Unlink, ExternalLink, Loader2 } from 'lucide-react';
import { useSettings, useUpdateSettings, usePreviewPattern } from '@/hooks/useSettings';
import {
  getAudibleStatus,
  getAudibleLoginUrl,
  authorizeAudible,
  disconnectAudible,
} from '@/api/client';
import { useToast } from '@/components/Toast';

const PRESETS = {
  chaptarr: '{Author}/{Series}/{SeriesPosition} - {Title} ({Year}) {EditionBracketed}',
  audiobookshelf: '{Author}/{Series}/Book {SeriesPosition} - {Year} - {Title} {NarratorBraced} {EditionBracketed}',
};

const TOKENS = [
  '{Author}',
  '{Series}',
  '{SeriesPosition}',
  '{Title}',
  '{Year}',
  '{Narrator}',
  '{NarratorBraced}',
  '{Edition}',
  '{EditionBracketed}',
];

export default function SettingsPage() {
  const { data: settings, isLoading } = useSettings();
  const updateSettings = useUpdateSettings();

  const toast = useToast();

  const [pattern, setPattern] = useState('');
  const [root, setRoot] = useState('');
  const [apiKey, setApiKey] = useState('');

  // Audible state
  const [audibleConnected, setAudibleConnected] = useState(false);
  const [audibleLocale, setAudibleLocale] = useState('us');
  const [audibleLoginUrl, setAudibleLoginUrl] = useState('');
  const [audibleResponseUrl, setAudibleResponseUrl] = useState('');
  const [audibleLoading, setAudibleLoading] = useState(false);

  const { data: preview } = usePreviewPattern(pattern);

  useEffect(() => {
    if (settings) {
      setPattern(settings.output_pattern);
      setRoot(settings.output_root);
      setApiKey(settings.google_books_api_key || '');
      if (settings.audible_locale) setAudibleLocale(settings.audible_locale);
    }
  }, [settings]);

  // Fetch Audible status on mount
  useEffect(() => {
    getAudibleStatus()
      .then((status) => {
        setAudibleConnected(status.connected);
        if (status.locale) setAudibleLocale(status.locale);
      })
      .catch(() => {});
  }, []);

  const handleSave = () => {
    updateSettings.mutate(
      {
        output_pattern: pattern,
        output_root: root,
        google_books_api_key: apiKey || null,
        audible_locale: audibleLocale,
      },
      {
        onSuccess: () => toast.success('Settings saved'),
        onError: () => toast.error('Failed to save settings'),
      },
    );
  };

  const handleAudibleConnect = async () => {
    setAudibleLoading(true);
    try {
      const { login_url } = await getAudibleLoginUrl(audibleLocale);
      setAudibleLoginUrl(login_url);
    } catch (e) {
      toast.error('Failed to generate Audible login URL');
    } finally {
      setAudibleLoading(false);
    }
  };

  const handleAudibleAuthorize = async () => {
    if (!audibleResponseUrl.trim()) {
      toast.error('Please paste the redirect URL');
      return;
    }
    setAudibleLoading(true);
    try {
      const status = await authorizeAudible(audibleResponseUrl, audibleLocale);
      setAudibleConnected(status.connected);
      setAudibleLoginUrl('');
      setAudibleResponseUrl('');
      toast.success('Audible connected successfully!');
    } catch (e) {
      toast.error('Audible authorization failed. Please try again.');
    } finally {
      setAudibleLoading(false);
    }
  };

  const handleAudibleDisconnect = async () => {
    try {
      await disconnectAudible();
      setAudibleConnected(false);
      toast.success('Audible disconnected');
    } catch {
      toast.error('Failed to disconnect Audible');
    }
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

        {/* Audible Integration */}
        <div
          className="rounded-lg border p-5"
          style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center justify-between mb-1">
            <label className="text-sm font-medium">Audible Integration</label>
            {audibleConnected ? (
              <span
                className="px-2 py-0.5 rounded text-xs font-medium"
                style={{ backgroundColor: '#16653422', color: '#22c55e' }}
              >
                Connected
              </span>
            ) : (
              <span
                className="px-2 py-0.5 rounded text-xs font-medium"
                style={{ backgroundColor: '#dc262622', color: '#ef4444' }}
              >
                Not Connected
              </span>
            )}
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
            Connect your Audible account to search for audiobook metadata including narrator and series info.
          </p>

          {/* Locale */}
          <div className="mb-3">
            <label className="block text-xs mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Marketplace
            </label>
            <select
              value={audibleLocale}
              onChange={(e) => setAudibleLocale(e.target.value)}
              disabled={audibleConnected}
              className="rounded border px-2 py-1.5 text-sm outline-none"
              style={{
                backgroundColor: 'var(--color-bg)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text)',
              }}
            >
              <option value="us">US (audible.com)</option>
              <option value="uk">UK (audible.co.uk)</option>
              <option value="ca">CA (audible.ca)</option>
              <option value="au">AU (audible.com.au)</option>
              <option value="de">DE (audible.de)</option>
              <option value="fr">FR (audible.fr)</option>
              <option value="it">IT (audible.it)</option>
              <option value="in">IN (audible.in)</option>
              <option value="jp">JP (audible.co.jp)</option>
              <option value="es">ES (audible.es)</option>
            </select>
          </div>

          {audibleConnected ? (
            <button
              onClick={handleAudibleDisconnect}
              className="flex items-center gap-2 px-3 py-2 rounded text-sm border"
              style={{ borderColor: '#ef4444', color: '#ef4444' }}
            >
              <Unlink size={14} />
              Disconnect Audible
            </button>
          ) : (
            <>
              {!audibleLoginUrl ? (
                <button
                  onClick={handleAudibleConnect}
                  disabled={audibleLoading}
                  className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium text-white"
                  style={{ backgroundColor: '#f59e0b' }}
                >
                  {audibleLoading ? <Loader2 size={14} className="animate-spin" /> : <Link size={14} />}
                  Connect Audible Account
                </button>
              ) : (
                <div className="space-y-3">
                  <div className="rounded p-3 text-xs" style={{ backgroundColor: 'var(--color-bg)' }}>
                    <p className="font-medium mb-1">Step 1: Open this URL in your browser and log in:</p>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={audibleLoginUrl}
                        readOnly
                        className="flex-1 rounded border px-2 py-1 text-xs font-mono outline-none"
                        style={{
                          backgroundColor: 'var(--color-surface)',
                          borderColor: 'var(--color-border)',
                          color: 'var(--color-text-muted)',
                        }}
                      />
                      <a
                        href={audibleLoginUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 px-2 py-1 rounded text-xs border"
                        style={{ borderColor: 'var(--color-border)', color: 'var(--color-primary)' }}
                      >
                        <ExternalLink size={12} />
                        Open
                      </a>
                    </div>
                  </div>
                  <div className="rounded p-3 text-xs" style={{ backgroundColor: 'var(--color-bg)' }}>
                    <p className="font-medium mb-1">
                      Step 2: After logging in, you&apos;ll see a &quot;Page Not Found&quot; page. Copy the full URL from your browser&apos;s address bar and paste it here:
                    </p>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={audibleResponseUrl}
                        onChange={(e) => setAudibleResponseUrl(e.target.value)}
                        placeholder="https://www.amazon.com/ap/maplanding?..."
                        className="flex-1 rounded border px-2 py-1.5 text-xs font-mono outline-none"
                        style={{
                          backgroundColor: 'var(--color-surface)',
                          borderColor: 'var(--color-border)',
                          color: 'var(--color-text)',
                        }}
                      />
                      <button
                        onClick={handleAudibleAuthorize}
                        disabled={audibleLoading}
                        className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium text-white"
                        style={{ backgroundColor: 'var(--color-primary)' }}
                      >
                        {audibleLoading ? <Loader2 size={12} className="animate-spin" /> : 'Authorize'}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
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
