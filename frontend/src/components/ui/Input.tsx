import { forwardRef, useId } from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className = '', id: propId, ...props }, ref) => {
    const autoId = useId();
    const id = propId || autoId;

    return (
      <div>
        {label && (
          <label htmlFor={id} className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-muted)' }}>
            {label}
          </label>
        )}
        {hint && (
          <p className="text-xs mb-1.5" style={{ color: 'var(--color-text-muted)', opacity: 0.7 }}>
            {hint}
          </p>
        )}
        <input
          ref={ref}
          id={id}
          className={`w-full rounded border px-3 py-2 text-sm outline-none transition-colors focus:ring-2 focus:ring-[var(--color-primary)] disabled:opacity-50 ${className}`}
          style={{
            backgroundColor: 'var(--color-bg)',
            borderColor: error ? 'var(--color-danger)' : 'var(--color-border)',
            color: 'var(--color-text)',
          }}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          {...props}
        />
        {error && (
          <p id={`${id}-error`} className="text-xs mt-1" style={{ color: 'var(--color-danger)' }} role="alert">
            {error}
          </p>
        )}
      </div>
    );
  },
);

Input.displayName = 'Input';
export default Input;
