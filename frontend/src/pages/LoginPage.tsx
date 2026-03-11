import { useState } from 'react';
import { BookOpen, Loader2 } from 'lucide-react';
import { login } from '@/api/client';

interface Props {
  registrationOpen: boolean;
  onSuccess: () => void;
  onGoToRegister: () => void;
}

export default function LoginPage({ registrationOpen, onSuccess, onGoToRegister }: Props) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setError('');
    setLoading(true);
    try {
      await login(username.trim(), password);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ backgroundColor: 'var(--color-bg)' }}>
      <div
        className="w-full max-w-sm rounded-lg border p-8"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <div className="flex items-center justify-center gap-2 mb-6">
          <BookOpen size={28} style={{ color: 'var(--color-primary)' }} />
          <h1 className="text-xl font-bold">Audiobook Organizer</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              className="w-full rounded border px-3 py-2 text-sm outline-none focus:ring-2"
              style={{
                backgroundColor: 'var(--color-bg)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>
          <div>
            <label className="block text-sm mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border px-3 py-2 text-sm outline-none focus:ring-2"
              style={{
                backgroundColor: 'var(--color-bg)',
                borderColor: 'var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>

          {error && (
            <p className="text-xs" style={{ color: 'var(--color-danger)' }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded text-sm font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-primary)' }}
          >
            {loading && <Loader2 size={16} className="animate-spin" />}
            Log In
          </button>
        </form>

        {registrationOpen && (
          <p className="text-center text-xs mt-4" style={{ color: 'var(--color-text-muted)' }}>
            Don&apos;t have an account?{' '}
            <button
              onClick={onGoToRegister}
              className="underline"
              style={{ color: 'var(--color-primary)' }}
            >
              Create one
            </button>
          </p>
        )}
      </div>
    </div>
  );
}
