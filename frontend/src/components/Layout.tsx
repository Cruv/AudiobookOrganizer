import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
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

const navItems = [
  { to: '/', icon: FolderSearch, label: 'Scan' },
  { to: '/review', icon: CheckCircle, label: 'Review' },
  { to: '/organize', icon: FolderOutput, label: 'Organize' },
  { to: '/purge', icon: Trash2, label: 'Purge' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

interface Props {
  username?: string | null;
  isAdmin?: boolean;
}

export default function Layout({ username, isAdmin }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // ignore
    }
    window.location.reload();
  };

  const sidebarContent = (
    <>
      <div className="p-4 border-b flex items-center gap-2"
        style={{ borderColor: 'var(--color-border)' }}>
        <BookOpen size={24} style={{ color: 'var(--color-primary)' }} />
        <h1 className="text-lg font-bold">Audiobook Organizer</h1>
        <button
          onClick={() => setSidebarOpen(false)}
          className="ml-auto p-1 rounded hover:bg-[var(--color-surface-hover)] md:hidden"
          style={{ color: 'var(--color-text-muted)' }}
        >
          <X size={20} />
        </button>
      </div>
      <div className="flex-1 py-2">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            onClick={() => setSidebarOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                isActive
                  ? 'font-semibold'
                  : 'hover:bg-[var(--color-surface-hover)]'
              }`
            }
            style={({ isActive }) =>
              isActive
                ? { backgroundColor: 'var(--color-primary)', color: 'white' }
                : { color: 'var(--color-text-muted)' }
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </div>
      <div className="p-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
        {username && (
          <div className="flex items-center justify-between">
            <span className="text-xs truncate" style={{ color: 'var(--color-text-muted)' }}>
              {username}{isAdmin && ' (admin)'}
            </span>
            <button
              onClick={handleLogout}
              className="p-1.5 rounded hover:bg-[var(--color-surface-hover)]"
              style={{ color: 'var(--color-text-muted)' }}
              title="Log out"
            >
              <LogOut size={14} />
            </button>
          </div>
        )}
        <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)', opacity: 0.5 }}>
          v1.0.0
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
        >
          <nav
            className="w-64 h-full flex flex-col"
            style={{ backgroundColor: 'var(--color-surface)' }}
            onClick={(e) => e.stopPropagation()}
          >
            {sidebarContent}
          </nav>
        </div>
      )}

      {/* Desktop sidebar */}
      <nav className="hidden md:flex w-56 flex-shrink-0 border-r flex-col"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        {sidebarContent}
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6 pt-16 md:pt-6">
        <Outlet />
      </main>
    </div>
  );
}
