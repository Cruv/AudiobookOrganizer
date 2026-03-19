import { forwardRef, useId } from 'react';

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: { value: string; label: string }[];
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, options, className = '', id: propId, ...props }, ref) => {
    const autoId = useId();
    const id = propId || autoId;

    return (
      <div>
        {label && (
          <label htmlFor={id} className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-muted)' }}>
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={id}
          className={`rounded border px-2.5 py-2 text-sm outline-none transition-colors focus:ring-2 focus:ring-[var(--color-primary)] ${className}`}
          style={{
            backgroundColor: 'var(--color-bg)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-text)',
          }}
          {...props}
        >
          {options.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>
    );
  },
);

Select.displayName = 'Select';
export default Select;
