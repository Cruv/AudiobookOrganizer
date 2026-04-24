import { memo, useCallback, useEffect, useRef } from 'react';
import { Input } from '@/components/ui';

interface Props {
  /** Seeds the <input>'s default value ONCE at mount. Changing this
   * prop after mount has no effect (the field is uncontrolled). */
  initialValue: string;
  /** Stable callback — debounced. Must be wrapped in useCallback by
   * the caller so `memo` can keep this component from re-rendering. */
  onDebouncedChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  debounceMs?: number;
}

/**
 * Fully-isolated search input.
 *
 * Why this exists: the Review page re-renders on every state change
 * (filter dropdown, book list refetch, URL sync, paging, …). Even with
 * the parent's <input> uncontrolled, we kept seeing the caret drop
 * when the URL-sync effect fired setSearchParams and React-Router
 * cascaded through the routed tree.
 *
 * This component wraps <Input> in React.memo with props the parent
 * guarantees are stable (useState initializer for the initial value,
 * useCallback for the handler). The memo short-circuits every parent
 * re-render — if the props are reference-equal, the <Input> never
 * reconciles, the <input> DOM node is never touched, and focus stays
 * exactly where the user put it.
 *
 * Typing does NOT go through React state. onChange starts a debounce
 * timer; when it expires we call onDebouncedChange with the value.
 * The browser owns the input's displayed text the whole time.
 */
function SearchFieldImpl({
  initialValue,
  onDebouncedChange,
  placeholder,
  label = 'Search',
  debounceMs = 300,
}: Props) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const value = e.target.value;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => onDebouncedChange(value), debounceMs);
    },
    [onDebouncedChange, debounceMs],
  );

  // Cleanup on unmount so a stale timer doesn't push a value into a
  // parent that's already moved on.
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return (
    <Input
      label={label}
      type="text"
      defaultValue={initialValue}
      onChange={handleChange}
      placeholder={placeholder}
    />
  );
}

const SearchField = memo(SearchFieldImpl);
export default SearchField;
