'use client';

import { useTranslations } from 'next-intl';
import { Link } from '@/navigation';

export function Footer() {
  const year = new Date().getFullYear();
  const t = useTranslations('Footer');

  return (
    <footer className="bg-muted/30 border-t">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-6 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <div className="space-y-1">
          <p className="text-sm font-medium">{t('title')}</p>
          <p className="text-muted-foreground text-xs sm:text-sm">
            {t('description')}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <Link
            href="/repos"
            className="text-muted-foreground hover:text-foreground text-xs transition-colors sm:text-sm"
          >
            {t('repositories')}
          </Link>
          <p className="text-muted-foreground text-xs sm:text-sm">
            {t('rights', { year })}
          </p>
        </div>
      </div>
    </footer>
  );
}
