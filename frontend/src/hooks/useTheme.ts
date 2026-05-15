import { useCallback, useEffect, useState } from 'react';

/**
 * Light/dark theme hook. Persists the user's choice in localStorage
 * and applies it via `data-theme` on the <html> element. Falls back
 * to the OS's `prefers-color-scheme` if no choice is stored.
 */
type Theme = 'light' | 'dark';

const STORAGE_KEY = 'ao.theme';

function readInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark';
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  if (window.matchMedia?.('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(readInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute('data-theme', theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // ignore (private browsing, full quota, etc.) — applying the
      // attribute already worked, only persistence failed.
    }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === 'dark' ? 'light' : 'dark'));
  }, []);

  return { theme, setTheme, toggle };
}
