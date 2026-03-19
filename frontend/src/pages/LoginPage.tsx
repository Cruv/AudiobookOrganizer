import { useState } from 'react';
import { BookOpen } from 'lucide-react';
import { login } from '@/api/client';
import { Button, Input } from '@/components/ui';

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
          <Input
            label="Username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
          />
          <Input
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            error={error}
          />

          <Button
            type="submit"
            loading={loading}
            disabled={!username.trim() || !password}
            className="w-full"
          >
            Log In
          </Button>
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
