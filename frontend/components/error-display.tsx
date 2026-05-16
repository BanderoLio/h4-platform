'use client';

import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { useTranslations } from 'next-intl';

type ErrorDisplayProps = {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
};

export function ErrorDisplay({
  title,
  message,
  onRetry,
  retryLabel,
  className,
}: ErrorDisplayProps) {
  const t = useTranslations('Common');
  const displayTitle = title ?? t('somethingWentWrong');
  const displayRetryLabel = retryLabel ?? t('tryAgain');
  return (
    <Alert variant="destructive" className={className}>
      <AlertCircle className="h-4 w-4" aria-hidden="true" />
      <AlertTitle>{displayTitle}</AlertTitle>
      <AlertDescription>
        <p>{message}</p>
        {onRetry && (
          <Button
            variant="outline"
            size="sm"
            onClick={onRetry}
            className="mt-4"
            aria-label={displayRetryLabel}
          >
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            {displayRetryLabel}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}
