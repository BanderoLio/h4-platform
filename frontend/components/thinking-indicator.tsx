'use client';

import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';

type ThinkingIndicatorProps = {
  label: string;
  className?: string;
};

/**
 * "Agent is working" indicator for a pending assistant message — the same
 * affordance Cursor / Claude Code show while a response is being generated:
 * animated dots, a pulsing label, and a live elapsed-time counter.
 */
export function ThinkingIndicator({
  label,
  className,
}: ThinkingIndicatorProps) {
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const intervalId = window.setInterval(() => {
      setSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  return (
    <div
      className={cn(
        'text-muted-foreground flex items-center gap-2 text-sm',
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <span className="flex items-center gap-1" aria-hidden="true">
        <span className="bg-primary h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:-0.3s]" />
        <span className="bg-primary h-1.5 w-1.5 animate-bounce rounded-full [animation-delay:-0.15s]" />
        <span className="bg-primary h-1.5 w-1.5 animate-bounce rounded-full" />
      </span>
      <span className="animate-pulse">{label}</span>
      {seconds > 0 && (
        <span className="text-muted-foreground/70 text-xs tabular-nums">
          {seconds}s
        </span>
      )}
    </div>
  );
}
