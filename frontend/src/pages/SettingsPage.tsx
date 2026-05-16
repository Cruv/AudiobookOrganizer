import { useEffect, useState } from 'react';
import {
  Save, RotateCcw, Link, Unlink, ExternalLink, Copy, Trash2, UserPlus, Key, Plus,
} from 'lucide-react';
import { useSettings, useUpdateSettings, usePreviewPattern } from '@/hooks/useSettings';
import {
  getAudibleStatus,
  getAudibleLoginUrl,
  authorizeAudible,
  disconnectAudible,
  createInvite,
  getInvites,
  deleteInvite,
  listApiTokens,
  createApiToken,
  revokeApiToken,
  type ApiTokenItem,
} from '@/api/client';
import { useToast } from '@/components/Toast';
import { Button, Card, Input, Select, Toggle, StatusBadge } from '@/components/ui';
import { PageSkeleton } from '@/components/ui/Skeleton';
import type { InviteItem } from '@/types';

const PRESETS = {
  chaptarr: '{Author}/{Series}/{SeriesPosition} - {Title} ({Year}) {EditionBracketed}',
  audiobookshelf: '{Author}/{Series}/Book {SeriesPosition} - {Year} - {Title} {NarratorBraced} {EditionBracketed}',
};

const TOKENS = [
  '{Author}', '{Series}', '{SeriesPosition}', '{Title}',
  '{Year}', '{Narrator}', '{NarratorBraced}', '{Edition}', '{EditionBracketed}',
];

const LOCALE_OPTIONS = [
  { value: 'us', label: 'US (audible.com)' },
  { value: 'uk', label: 'UK (audible.co.uk)' },
  { value: 'ca', label: 'CA (audible.ca)' },
  { value: 'au', label: 'AU (audible.com.au)' },
  { value: 'de', label: 'DE (audible.de)' },
  { value: 'fr', label: 'FR (audible.fr)' },
  { value: 'it', label: 'IT (audible.it)' },
  { value: 'in', label: 'IN (audible.in)' },
  { value: 'jp', label: 'JP (audible.co.jp)' },
  { value: 'es', label: 'ES (audible.es)' },
];

interface SettingsPageProps {
  isAdmin?: boolean;
}

export default function SettingsPage({ isAdmin }: SettingsPageProps) {
  const { data: settings, isLoading } = useSettings();
  const updateSettings = useUpdateSettings();
  const toast = useToast();

  const [pattern, setPattern] = useState('');
  const [root, setRoot] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [writeTagsOnOrganize, setWriteTagsOnOrganize] = useState(false);

  // Audible state
  const [audibleConnected, setAudibleConnected] = useState(false);
  const [audibleLocale, setAudibleLocale] = useState('us');
  const [audibleLoginUrl, setAudibleLoginUrl] = useState('');
  const [audibleResponseUrl, setAudibleResponseUrl] = useState('');
  const [audibleSessionToken, setAudibleSessionToken] = useState('');
  const [audibleLoading, setAudibleLoading] = useState(false);

  // Invite state
  const [invites, setInvites] = useState<InviteItem[]>([]);
  const [registrationOpen, setRegistrationOpen] = useState(true);

  // API tokens state
  const [tokens, setTokens] = useState<ApiTokenItem[]>([]);
  const [newTokenName, setNewTokenName] = useState('');
  // The full plaintext is only available right after creation; we keep
  // it in component state until the user dismisses it.
  const [revealedToken, setRevealedToken] = useState<string | null>(null);

  const { data: preview } = usePreviewPattern(pattern);

  useEffect(() => {
    if (settings) {
      setPattern(settings.output_pattern);
      setRoot(settings.output_root);
      setApiKey(settings.google_books_api_key || '');
      if (settings.audible_locale) setAudibleLocale(settings.audible_locale);
      setWriteTagsOnOrganize(!!settings.write_tags_on_organize);
    }
  }, [settings]);

  useEffect(() => {
    getAudibleStatus()
      .then((status) => {
        setAudibleConnected(status.connected);
        if (status.locale) setAudibleLocale(status.locale);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    getInvites().then(setInvites).catch(() => {});
  }, [isAdmin]);

  useEffect(() => {
    // Tokens are per-user, not admin-gated — every logged-in user
    // sees their own.
    listApiTokens().then(setTokens).catch(() => {});
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    fetch('/api/auth/status', { cache: 'no-store', credentials: 'include' })
      .then((r) => r.json())
      .then((data) => {
        if (typeof data.registration_open === 'boolean') {
          setRegistrationOpen(data.registration_open);
        }
      })
      .catch(() => {});
  }, [isAdmin]);

  const handleSave = () => {
    updateSettings.mutate(
      {
        output_pattern: pattern,
        output_root: root,
        google_books_api_key: apiKey || null,
        audible_locale: audibleLocale,
        write_tags_on_organize: writeTagsOnOrganize,
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
      const { login_url, session_token } = await getAudibleLoginUrl(audibleLocale);
      setAudibleLoginUrl(login_url);
      setAudibleSessionToken(session_token);
      // Auto-copy to clipboard
      await navigator.clipboard.writeText(login_url);
      toast.success('Login URL copied to clipboard');
    } catch {
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
      const status = await authorizeAudible(audibleResponseUrl, audibleLocale, audibleSessionToken);
      setAudibleConnected(status.connected);
      setAudibleLoginUrl('');
      setAudibleResponseUrl('');
      setAudibleSessionToken('');
      toast.success('Audible connected successfully!');
    } catch {
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

  const handleCreateInvite = async () => {
    try {
      const invite = await createInvite();
      setInvites((prev) => [invite, ...prev]);
      const url = `${window.location.origin}?invite=${invite.token}`;
      await navigator.clipboard.writeText(url);
      toast.success('Invite link copied to clipboard');
    } catch {
      toast.error('Failed to create invite');
    }
  };

  const handleDeleteInvite = async (id: number) => {
    try {
      await deleteInvite(id);
      setInvites((prev) => prev.filter((i) => i.id !== id));
      toast.success('Invite revoked');
    } catch {
      toast.error('Failed to revoke invite');
    }
  };

  const handleCreateApiToken = async () => {
    const name = newTokenName.trim();
    if (!name) {
      toast.error('Give the token a name first');
      return;
    }
    try {
      const created = await createApiToken(name);
      setTokens((prev) => [
        {
          id: created.id, name: created.name,
          token_prefix: created.token_prefix,
          created_at: new Date().toISOString(),
          last_used_at: null, revoked: false,
        },
        ...prev,
      ]);
      setRevealedToken(created.token);
      setNewTokenName('');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to create token');
    }
  };

  const handleRevokeApiToken = async (id: number) => {
    try {
      await revokeApiToken(id);
      setTokens((prev) =>
        prev.map((t) => (t.id === id ? { ...t, revoked: true } : t)),
      );
      toast.success('Token revoked');
    } catch {
      toast.error('Failed to revoke token');
    }
  };

  const handleToggleRegistration = async () => {
    const newValue = !registrationOpen;
    try {
      await updateSettings.mutateAsync({
        registration_open: newValue ? 'true' : 'false',
      });
      setRegistrationOpen(newValue);
      toast.success(newValue ? 'Registration opened' : 'Registration closed');
    } catch {
      toast.error('Failed to update registration setting');
    }
  };

  if (isLoading) {
    return (
      <div className="max-w-2xl">
        <h1 className="text-2xl font-bold mb-6">Settings</h1>
        <PageSkeleton />
      </div>
    );
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      <div className="space-y-6">
        {/* Output Settings */}
        <Card header={<h2 className="text-sm font-semibold">Output Settings</h2>}>
          <div className="space-y-4">
            <Input
              label="Output Root Directory"
              hint="Base directory where organized audiobooks will be placed."
              type="text"
              value={root}
              onChange={(e) => setRoot(e.target.value)}
            />

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm font-medium" style={{ color: 'var(--color-text-muted)' }}>
                  Output Naming Pattern
                </label>
                <div className="flex gap-1.5">
                  <Button size="sm" variant="success" icon={<RotateCcw size={12} />} onClick={() => setPattern(PRESETS.audiobookshelf)}>
                    Audiobookshelf
                  </Button>
                  <Button size="sm" icon={<RotateCcw size={12} />} onClick={() => setPattern(PRESETS.chaptarr)}>
                    Chaptarr
                  </Button>
                </div>
              </div>
              <p className="text-xs mb-2" style={{ color: 'var(--color-text-muted)', opacity: 0.7 }}>
                Use tokens to define the folder structure. Segments with missing values are removed.
              </p>
              <input
                type="text"
                value={pattern}
                onChange={(e) => setPattern(e.target.value)}
                className="w-full rounded border px-3 py-2 text-sm font-mono outline-none mb-2 focus:ring-2 focus:ring-[var(--color-primary)]"
                style={{
                  backgroundColor: 'var(--color-bg)',
                  borderColor: 'var(--color-border)',
                  color: 'var(--color-text)',
                }}
              />
              <div className="flex flex-wrap gap-1.5 mb-3">
                {TOKENS.map((token) => (
                  <Button
                    key={token}
                    variant="secondary"
                    size="sm"
                    onClick={() => setPattern((prev) => prev + token)}
                  >
                    {token}
                  </Button>
                ))}
              </div>
              {preview && (
                <div className="rounded p-3 text-xs font-mono" style={{ backgroundColor: 'var(--color-bg)' }}>
                  <span style={{ color: 'var(--color-text-muted)' }}>Preview: </span>
                  <span style={{ color: 'var(--color-success)' }}>
                    {root}/{preview.preview}
                  </span>
                </div>
              )}
            </div>
          </div>
        </Card>

        {/* API Keys */}
        <Card header={<h2 className="text-sm font-semibold">API Keys</h2>}>
          <Input
            label="Google Books API Key"
            hint="Optional. Improves online lookup results. Get one at Google Cloud Console."
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Enter API key..."
          />
        </Card>

        {/* Tag write-back (opt-in, destructive) */}
        <Card header={<h2 className="text-sm font-semibold">Output options</h2>}>
          <div className="rounded p-3" style={{ backgroundColor: 'var(--color-bg)' }}>
            <Toggle
              label="Write corrected tags into organized files"
              description="When ON, organize patches title/author/album/year/narrator/series tags on the copied destination files via mutagen. Source files are NEVER touched. Off by default — tag writes are irreversible without re-organizing."
              checked={writeTagsOnOrganize}
              onChange={() => setWriteTagsOnOrganize((v) => !v)}
            />
          </div>
        </Card>

        {/* Audible Integration */}
        <Card
          header={
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold">Audible Integration</h2>
              <StatusBadge connected={audibleConnected} />
            </div>
          }
        >
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
            Connect your Audible account to search for audiobook metadata including narrator and series info.
          </p>

          <div className="mb-3">
            <Select
              label="Marketplace"
              value={audibleLocale}
              onChange={(e) => setAudibleLocale(e.target.value)}
              options={LOCALE_OPTIONS}
              disabled={audibleConnected}
            />
          </div>

          {audibleConnected ? (
            <Button
              variant="danger"
              size="sm"
              icon={<Unlink size={14} />}
              onClick={handleAudibleDisconnect}
            >
              Disconnect Audible
            </Button>
          ) : (
            <>
              {!audibleLoginUrl ? (
                <Button
                  icon={<Link size={14} />}
                  loading={audibleLoading}
                  onClick={handleAudibleConnect}
                  style={{ backgroundColor: '#f59e0b' }}
                >
                  Connect Audible Account
                </Button>
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
                      <Button
                        variant="secondary"
                        size="sm"
                        icon={<Copy size={12} />}
                        onClick={() => {
                          navigator.clipboard.writeText(audibleLoginUrl);
                          toast.success('URL copied');
                        }}
                      >
                        Copy
                      </Button>
                      <a
                        href={audibleLoginUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-xs border"
                        style={{ borderColor: 'var(--color-border)', color: 'var(--color-primary)' }}
                      >
                        <ExternalLink size={12} />
                        Open
                      </a>
                    </div>
                  </div>
                  <div className="rounded p-3 text-xs" style={{ backgroundColor: 'var(--color-bg)' }}>
                    <p className="font-medium mb-1">
                      Step 2: After logging in, copy the full URL from your browser&apos;s address bar and paste it here:
                    </p>
                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={audibleResponseUrl}
                        onChange={(e) => setAudibleResponseUrl(e.target.value)}
                        placeholder="https://www.amazon.com/ap/maplanding?..."
                        className="flex-1 rounded border px-2 py-1.5 text-xs font-mono outline-none focus:ring-2 focus:ring-[var(--color-primary)]"
                        style={{
                          backgroundColor: 'var(--color-surface)',
                          borderColor: 'var(--color-border)',
                          color: 'var(--color-text)',
                        }}
                      />
                      <Button
                        size="sm"
                        loading={audibleLoading}
                        onClick={handleAudibleAuthorize}
                      >
                        Authorize
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>

        {/* Admin: User Management */}
        {isAdmin && (
          <Card header={<h2 className="text-sm font-semibold">User Management</h2>}>
            <p className="text-xs mb-4" style={{ color: 'var(--color-text-muted)' }}>
              Control who can create accounts and manage invite links.
            </p>

            <div className="rounded p-3 mb-4" style={{ backgroundColor: 'var(--color-bg)' }}>
              <Toggle
                label="Open Registration"
                description={registrationOpen ? 'Anyone can create an account' : 'Invite required to register'}
                checked={registrationOpen}
                onChange={handleToggleRegistration}
              />
            </div>

            <div className="mb-3">
              <Button
                icon={<UserPlus size={14} />}
                onClick={handleCreateInvite}
              >
                Generate Invite Link
              </Button>
            </div>

            {invites.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium" style={{ color: 'var(--color-text-muted)' }}>
                  Active Invites
                </p>
                {invites.map((invite) => (
                  <div
                    key={invite.id}
                    className="flex items-center justify-between rounded p-2.5 text-xs"
                    style={{ backgroundColor: 'var(--color-bg)' }}
                  >
                    <div className="flex-1 min-w-0">
                      <span className="font-mono truncate block" style={{ color: 'var(--color-text-muted)' }}>
                        ...{invite.token.slice(-12)}
                      </span>
                      <span style={{ color: 'var(--color-text-muted)', opacity: 0.6 }}>
                        {invite.used ? 'Used' : `Expires ${new Date(invite.expires_at + 'Z').toLocaleDateString()}`}
                      </span>
                    </div>
                    {!invite.used && (
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Copy size={12} />}
                          onClick={() => {
                            navigator.clipboard.writeText(`${window.location.origin}?invite=${invite.token}`);
                            toast.success('Invite link copied');
                          }}
                          title="Copy invite link"
                          aria-label="Copy invite link"
                        />
                        <Button
                          variant="ghost"
                          size="sm"
                          icon={<Trash2 size={12} />}
                          onClick={() => handleDeleteInvite(invite.id)}
                          title="Revoke invite"
                          aria-label="Revoke invite"
                          style={{ color: 'var(--color-danger)' }}
                        />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {/* API Tokens (per-user, all logged-in users see their own) */}
        <Card header={<h2 className="text-sm font-semibold">API Tokens</h2>}>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
            Long-lived tokens for third-party automation (Sonarr/Radarr-style
            downloaders, custom webhooks). Send as <code>Authorization: Bearer
            &lt;token&gt;</code>. Each token is shown only once when created
            — copy it then.
          </p>

          {revealedToken && (
            <div
              className="rounded p-3 mb-3 border"
              style={{
                borderColor: 'var(--color-warning)',
                backgroundColor: 'rgba(245,158,11,0.08)',
              }}
            >
              <p className="text-xs font-medium mb-2" style={{ color: 'var(--color-warning)' }}>
                Copy this token now — it won't be shown again.
              </p>
              <div className="flex items-center gap-2">
                <code
                  className="flex-1 text-xs font-mono break-all p-2 rounded"
                  style={{ backgroundColor: 'var(--color-bg)' }}
                >
                  {revealedToken}
                </code>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Copy size={12} />}
                  onClick={() => {
                    navigator.clipboard.writeText(revealedToken);
                    toast.success('Token copied');
                  }}
                  title="Copy token"
                >
                  Copy
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setRevealedToken(null)}
                  title="Dismiss"
                >
                  Dismiss
                </Button>
              </div>
            </div>
          )}

          <div className="flex gap-2 mb-4">
            <Input
              type="text"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreateApiToken()}
              placeholder="Token name (e.g. sonarr)"
              className="flex-1"
            />
            <Button icon={<Plus size={14} />} onClick={handleCreateApiToken}>
              Create
            </Button>
          </div>

          {tokens.length > 0 ? (
            <div className="space-y-2">
              {tokens.map((t) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between rounded p-2.5 text-xs"
                  style={{
                    backgroundColor: 'var(--color-bg)',
                    opacity: t.revoked ? 0.5 : 1,
                  }}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Key size={12} style={{ color: 'var(--color-text-muted)' }} />
                    <div className="min-w-0">
                      <p className="font-medium truncate">{t.name}</p>
                      <p
                        className="font-mono truncate"
                        style={{ color: 'var(--color-text-muted)' }}
                      >
                        {t.token_prefix}…
                        {t.revoked && (
                          <span className="ml-2" style={{ color: 'var(--color-danger)' }}>
                            (revoked)
                          </span>
                        )}
                      </p>
                    </div>
                  </div>
                  {!t.revoked && (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<Trash2 size={12} />}
                      onClick={() => handleRevokeApiToken(t.id)}
                      title="Revoke token"
                      aria-label={`Revoke ${t.name}`}
                      style={{ color: 'var(--color-danger)' }}
                    />
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
              No tokens yet. Create one to wire the app into a downloader.
            </p>
          )}
        </Card>

        {/* Save */}
        <Button
          icon={<Save size={16} />}
          loading={updateSettings.isPending}
          onClick={handleSave}
        >
          Save Settings
        </Button>
      </div>
    </div>
  );
}
