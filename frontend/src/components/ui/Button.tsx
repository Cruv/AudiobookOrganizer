import { forwardRef } from 'react';
import { Loader2 } from 'lucide-react';

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'success' | 'ghost';
type ButtonSize = 'sm' | 'md';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
}

const variantStyles: Record<ButtonVariant, { bg: string; color: string; border?: string; hoverBg?: string }> = {
  primary: { bg: 'var(--color-primary)', color: 'white' },
  secondary: { bg: 'transparent', color: 'var(--color-text-muted)', border: 'var(--color-border)', hoverBg: 'var(--color-surface-hover)' },
  danger: { bg: 'var(--color-danger)', color: 'white' },
  success: { bg: 'var(--color-success)', color: 'white' },
  ghost: { bg: 'transparent', color: 'var(--color-text-muted)', hoverBg: 'var(--color-surface-hover)' },
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2 text-sm gap-2',
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', loading, icon, children, disabled, className = '', style, ...props }, ref) => {
    const v = variantStyles[variant];
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={`inline-flex items-center justify-center font-medium rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${sizeClasses[size]} ${className}`}
        style={{
          backgroundColor: v.bg,
          color: v.color,
          border: v.border ? `1px solid ${v.border}` : 'none',
          ...style,
        }}
        {...props}
      >
        {loading ? <Loader2 size={size === 'sm' ? 14 : 16} className="animate-spin" /> : icon}
        {children}
      </button>
    );
  },
);

Button.displayName = 'Button';
export default Button;
