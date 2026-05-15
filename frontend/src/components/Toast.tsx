import { createContext, useCallback, useContext, useRef, useState } from 'react';
import { CheckCircle, X, AlertCircle } from 'lucide-react';

interface ToastItem {
  id: string;
  message: string;
  type: 'success' | 'error';
}

interface ToastContextValue {
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  // Per-provider counter (was a module-level let, which collided
  // across HMR reloads and produced duplicate React keys for toasts
  // that crossed a reload boundary).
  const counterRef = useRef(0);

  const addToast = useCallback((message: string, type: 'success' | 'error') => {
    counterRef.current += 1;
    const id = `${Date.now()}-${counterRef.current}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  const success = useCallback((message: string) => addToast(message, 'success'), [addToast]);
  const error = useCallback((message: string) => addToast(message, 'error'), [addToast]);

  const dismiss = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ success, error }}>
      {children}
      <div
        className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2"
        aria-live="polite"
        aria-atomic="false"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.type === 'error' ? 'alert' : 'status'}
            className="flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm min-w-[280px] animate-[slideIn_0.2s_ease-out]"
            style={{
              backgroundColor: toast.type === 'success' ? '#166534' : '#991b1b',
              color: toast.type === 'success' ? '#bbf7d0' : '#fecaca',
            }}
          >
            {toast.type === 'success' ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
            <span className="flex-1">{toast.message}</span>
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              className="opacity-60 hover:opacity-100"
              aria-label="Dismiss notification"
            >
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
