import { useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  BookOpen,
  CheckCircle,
  FolderSearch,
  LogOut,
  Menu,
  Settings,
  Trash2,
  FolderOutput,
  X,
} from 'lucide-react';
import { logout } from '@/api/client';

const workflowSteps = [
  { to: '/', icon: FolderSearch, label: 'Scan', step: 1 },
  { to: '/review', icon: CheckCircle, label: 'Review', step: 2 },
  { to: '/organize', icon: FolderOutput, label: 'Organize', step: 3 },
  { to: '/purge', icon: Trash2, label: 'Purge', step: 4 },
];

interface Props {
  username?: string | null;
  isAdmin?: boolean;
}

export default function Layout({ username, isAdmin }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  // Close mobile sidebar on Escape
  useEffect(() => {
    if (!sidebarOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [sidebarOpen]);

  // Close mobile sidebar on route change
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // ignore
    }
    window.location.reload();
  };

  // Determine current workflow step for visual indicator
  const currentStepIndex = workflowSteps.findIndex((s) => s.to === location.pathname);

  const sidebarContent = (
    <>
      {/* Brand */}
      <div className="p-4 border-b flex items-center gap-2" style={{ borderColor: 'var(--color-border)' }}>
        <BookOpen size={22} style={{ color: 'var(--color-primary)' }} />
        <h1 className="text-base font-bold flex-1">Audiobook Organizer</h1>
        <button
          onClick={() => setSidebarOpen(false)}
          className="p-1 rounded hover:bg-[var(--color-surface-hover)] md:hidden"
          style={{ color: 'var(--color-text-muted)' }}
          aria-label="Close navigation"
        >
          <X size={20} />
        </button>
      </div>

      {/* Workflow steps */}
      <div className="flex-1 py-3">
        <p className="px-4 text-[10px] font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)', opacity: 0.6 }}>
          Workflow
        </p>
        {workflowSteps.map(({ to, icon: Icon, label, step }) => {
          const isActive = location.pathname === to;
          const isPast = currentStepIndex > step - 1;
          return (
            <NavLink
              key={to}
              to={to}
              className="flex items-center gap-3 px-4 py-2.5 text-sm transition-colors relative"
              style={
                isActive
                  ? { backgroundColor: 'var(--color-primary)', color: 'white' }
                  : { color: isPast ? 'var(--color-text)' : 'var(--color-text-muted)' }
              }
            >
              {/* Step number */}
              <span
                className="w-5 h-5 rounded-full text-[10px] font-bold flex items-center justify-center flex-shrink-0"
                style={
                  isActive
                    ? { backgroundColor: 'rgba(255,255,255,0.2)', color: 'white' }
                    : isPast
                    ? { backgroundColor: 'var(--color-success)', color: 'white' }
                    : { backgroundColor: 'var(--color-surface-hover)', color: 'var(--color-text-muted)' }
                }
              >
                {isPast && !isActive ? '\u2713' : step}
              </span>
              <Icon size={16} />
              {label}
            </NavLink>
          );
        })}

        {/* Separator + Settings */}
        <div className="mx-4 my-3 border-t" style={{ borderColor: 'var(--color-border)' }} />
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
              isActive ? 'font-semibold' : 'hover:bg-[var(--color-surface-hover)]'
            }`
          }
          style={({ isActive }) =>
            isActive
              ? { backgroundColor: 'var(--color-primary)', color: 'white' }
              : { color: 'var(--color-text-muted)' }
          }
        >
          <Settings size={16} />
          Settings
        </NavLink>
      </div>

      {/* User footer */}
      <div className="p-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
        {username && (
          <div className="flex items-center justify-between">
            <span className="text-xs truncate" style={{ color: 'var(--color-text-muted)' }}>
              {username}
              {isAdmin && (
                <span className="ml-1 px-1 py-0.5 rounded text-[10px]" style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}>
                  admin
                </span>
              )}
            </span>
            <button
              onClick={handleLogout}
              className="p-1.5 rounded hover:bg-[var(--color-surface-hover)]"
              style={{ color: 'var(--color-text-muted)' }}
              title="Log out"
              aria-label="Log out"
            >
              <LogOut size={14} />
            </button>
          </div>
        )}
        <p className="text-[10px] mt-1" style={{ color: 'var(--color-text-muted)', opacity: 0.4 }}>
          v1.1.0
        </p>
      </div>
    </>
  );

  return (
    <div className="flex h-screen">
      {/* Mobile header */}
      <div
        className="fixed top-0 left-0 right-0 z-40 flex items-center gap-3 px-4 py-3 border-b md:hidden"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
      >
        <button
          onClick={() => setSidebarOpen(true)}
          className="p-1 rounded hover:bg-[var(--color-surface-hover)]"
          style={{ color: 'var(--color-text-muted)' }}
          aria-label="Open navigation"
          aria-expanded={sidebarOpen}
        >
          <Menu size={22} />
        </button>
        <BookOpen size={20} style={{ color: 'var(--color-primary)' }} />
        <span className="font-semibold text-sm">Audiobook Organizer</span>
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-label="Close navigation"
        >
          <nav
            className="w-64 h-full flex flex-col"
            style={{ backgroundColor: 'var(--color-surface)' }}
            onClick={(e) => e.stopPropagation()}
            aria-label="Navigation"
          >
            {sidebarContent}
          </nav>
        </div>
      )}

      {/* Desktop sidebar */}
      <nav
        className="hidden md:flex w-56 flex-shrink-0 border-r flex-col"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
        aria-label="Navigation"
      >
        {sidebarContent}
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6 pt-16 md:pt-6">
        <Outlet />
      </main>
    </div>
  );
}
