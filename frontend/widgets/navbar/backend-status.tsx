'use client';

import { useQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { apiClient } from '@/lib/api-client';
import type { Endpoint } from '@/lib/types';
import { useMounted } from '@/hooks/use-mounted';
import { cn } from '@/lib/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

const HEALTH_ENDPOINT: Endpoint<'/health'> = '/health';
const HEALTH_POLL_INTERVAL_MS = 15_000;

type HealthResponse = { status: string };

async function fetchBackendHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse, '/health'>(
    HEALTH_ENDPOINT,
  );
  return response.data;
}

type ConnectionState = 'checking' | 'online' | 'offline';

/**
 * Live backend reachability badge.
 *
 * Polls the BFF proxy's `/health` passthrough so the user can tell at a
 * glance whether scan requests will reach the backend.
 */
export function BackendStatus() {
  const t = useTranslations('BackendStatus');
  const mounted = useMounted();

  const { data, isError, isLoading } = useQuery({
    queryKey: ['backend-health'],
    queryFn: fetchBackendHealth,
    refetchInterval: HEALTH_POLL_INTERVAL_MS,
    refetchOnWindowFocus: true,
    retry: false,
    staleTime: HEALTH_POLL_INTERVAL_MS,
  });

  // Render a neutral state until mounted to avoid a hydration mismatch.
  const state: ConnectionState =
    !mounted || isLoading
      ? 'checking'
      : isError || data?.status !== 'ok'
        ? 'offline'
        : 'online';

  const dotClass = {
    checking: 'bg-muted-foreground/50',
    online: 'bg-emerald-500',
    offline: 'bg-destructive',
  }[state];

  const label = {
    checking: t('checking'),
    online: t('online'),
    offline: t('offline'),
  }[state];

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className="text-muted-foreground inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs"
          role="status"
          aria-label={`${t('label')}: ${label}`}
        >
          <span
            className={cn(
              'h-2 w-2 shrink-0 rounded-full',
              dotClass,
              state === 'checking' && 'animate-pulse',
            )}
            aria-hidden="true"
          />
          <span className="hidden sm:inline">{label}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {state === 'offline' ? t('offlineHint') : t('label')}
      </TooltipContent>
    </Tooltip>
  );
}
