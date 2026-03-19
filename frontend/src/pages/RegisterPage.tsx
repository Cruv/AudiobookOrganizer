import { useState } from 'react';
import { BookOpen, Check, X as XIcon } from 'lucide-react';
import { register } from '@/api/client';
import { Button, Input } from '@/components/ui';

interface Props {
  inviteToken?: string;
  isFirstUser?: boolean;
  onSuccess: () => void;
  onGoToLogin: () => void;
}

export default function RegisterPage({ inviteToken, isFirstUser, onSuccess, onGoToLogin }: Props) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const passwordLong = password.length >= 8;
  const passwordsMatch = password === confirmPassword && confirmPassword.length > 0;
  const showValidation = password.length > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    setError('');
    setLoading(true);
    try {
      await register(username.trim(), password, inviteToken);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
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
        <div className="flex items-center justify-center gap-2 mb-2">
          <BookOpen size={28} style={{ color: 'var(--color-primary)' }} />
          <h1 className="text-xl font-bold">Audiobook Organizer</h1>
        </div>
        <p className="text-center text-sm mb-6" style={{ color: 'var(--color-text-muted)' }}>
          {isFirstUser ? 'Create your admin account to get started.' : 'Create an account'}
        </p>

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
            autoComplete="new-password"
          />
          <Input
            label="Confirm Password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
          />

          {showValidation && (
            <div className="space-y-1">
              <ValidationHint passed={passwordLong} text="At least 8 characters" />
              {confirmPassword.length > 0 && (
                <ValidationHint passed={passwordsMatch} text="Passwords match" />
              )}
            </div>
          )}

          {error && (
            <p className="text-xs" style={{ color: 'var(--color-danger)' }} role="alert">
              {error}
            </p>
          )}

          <Button
            type="submit"
            loading={loading}
            disabled={!username.trim() || !password || !confirmPassword}
            className="w-full"
          >
            {isFirstUser ? 'Create Admin Account' : 'Create Account'}
          </Button>
        </form>

        {!isFirstUser && (
          <p className="text-center text-xs mt-4" style={{ color: 'var(--color-text-muted)' }}>
            Already have an account?{' '}
            <button
              onClick={onGoToLogin}
              className="underline"
              style={{ color: 'var(--color-primary)' }}
            >
              Log in
            </button>
          </p>
        )}
      </div>
    </div>
  );
}

function ValidationHint({ passed, text }: { passed: boolean; text: string }) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {passed ? (
        <Check size={12} style={{ color: 'var(--color-success)' }} />
      ) : (
        <XIcon size={12} style={{ color: 'var(--color-text-muted)' }} />
      )}
      <span style={{ color: passed ? 'var(--color-success)' : 'var(--color-text-muted)' }}>
        {text}
      </span>
    </div>
  );
}
