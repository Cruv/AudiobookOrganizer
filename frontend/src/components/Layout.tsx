import { NavLink, Outlet } from 'react-router-dom';
import {
  BookOpen,
  CheckCircle,
  FolderSearch,
  Settings,
  Trash2,
  FolderOutput,
} from 'lucide-react';

const navItems = [
  { to: '/', icon: FolderSearch, label: 'Scan' },
  { to: '/review', icon: CheckCircle, label: 'Review' },
  { to: '/organize', icon: FolderOutput, label: 'Organize' },
  { to: '/purge', icon: Trash2, label: 'Purge' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function Layout() {
  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <nav className="w-56 flex-shrink-0 border-r flex flex-col"
        style={{ backgroundColor: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>
        <div className="p-4 border-b flex items-center gap-2"
          style={{ borderColor: 'var(--color-border)' }}>
          <BookOpen size={24} style={{ color: 'var(--color-primary)' }} />
          <h1 className="text-lg font-bold">AudioOrganizer</h1>
        </div>
        <div className="flex-1 py-2">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
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
        <div className="p-3 text-xs" style={{ color: 'var(--color-text-muted)' }}>
          Audiobook Organizer v0.1
        </div>
      </nav>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
