import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from '@/components/Layout';
import { ToastProvider } from '@/components/Toast';
import ScanPage from '@/pages/ScanPage';
import ReviewPage from '@/pages/ReviewPage';
import OrganizePage from '@/pages/OrganizePage';
import PurgePage from '@/pages/PurgePage';
import SettingsPage from '@/pages/SettingsPage';
import LoginPage from '@/pages/LoginPage';
import RegisterPage from '@/pages/RegisterPage';
import ErrorBoundary from '@/components/ErrorBoundary';
import { getAuthStatus } from '@/api/client';
import type { AuthStatus } from '@/types';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
    },
  },
});

function AuthGate() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [view, setView] = useState<'login' | 'register'>('login');
  const [inviteToken, setInviteToken] = useState<string | undefined>();

  const checkAuth = () => {
    getAuthStatus()
      .then(setAuth)
      .catch(() =>
        setAuth({
          logged_in: false,
          username: null,
          is_admin: false,
          registration_open: true,
          has_users: false,
        }),
      );
  };

  useEffect(() => {
    checkAuth();
    // Check for invite token in URL
    const params = new URLSearchParams(window.location.search);
    const invite = params.get('invite');
    if (invite) {
      setInviteToken(invite);
      setView('register');
    }
  }, []);

  if (auth === null) {
    return null; // Loading
  }

  // No users yet — show registration (first-run setup)
  if (!auth.has_users) {
    return (
      <RegisterPage
        isFirstUser
        onSuccess={checkAuth}
        onGoToLogin={() => setView('login')}
      />
    );
  }

  // Not logged in
  if (!auth.logged_in) {
    if (view === 'register' && (auth.registration_open || inviteToken)) {
      return (
        <RegisterPage
          inviteToken={inviteToken}
          onSuccess={() => {
            setView('login');
            checkAuth();
          }}
          onGoToLogin={() => setView('login')}
        />
      );
    }
    return (
      <LoginPage
        registrationOpen={auth.registration_open}
        onSuccess={checkAuth}
        onGoToRegister={() => setView('register')}
      />
    );
  }

  // Logged in — show app
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout username={auth.username} isAdmin={auth.is_admin} />}>
          <Route path="/" element={<ErrorBoundary><ScanPage /></ErrorBoundary>} />
          <Route path="/review" element={<ErrorBoundary><ReviewPage /></ErrorBoundary>} />
          <Route path="/organize" element={<ErrorBoundary><OrganizePage /></ErrorBoundary>} />
          <Route path="/purge" element={<ErrorBoundary><PurgePage /></ErrorBoundary>} />
          <Route path="/settings" element={<ErrorBoundary><SettingsPage isAdmin={auth.is_admin} /></ErrorBoundary>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthGate />
      </ToastProvider>
    </QueryClientProvider>
  );
}
