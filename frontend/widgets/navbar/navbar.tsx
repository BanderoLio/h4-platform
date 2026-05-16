'use client';

import { Shield } from 'lucide-react';
import { SettingsMenu } from '@/components/settings-menu';
import { cn } from '@/lib/utils';
import { Link, usePathname } from '@/navigation';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { BackendStatus } from '@/widgets/navbar/backend-status';

export function Navbar({ titleFont }: { titleFont: string }) {
  const t = useTranslations('Navbar');
  const pathname = usePathname();
  const isRepositoriesPage = pathname?.includes('/repos');

  return (
    <nav
      className="bg-background/95 supports-backdrop-filter:bg-background/80 sticky top-0 z-20 border-b px-4 py-3 backdrop-blur sm:px-6"
      aria-label={t('mainAria')}
    >
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4">
        <Link href="/" className="flex min-w-0 items-center gap-2">
          <span className="bg-primary/10 text-primary inline-flex h-9 w-9 items-center justify-center rounded-md border">
            <Shield className="h-4 w-4" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p
              className={cn(
                'truncate text-base font-semibold sm:text-lg',
                titleFont,
              )}
            >
              {t('title')}
            </p>
            <p className="text-muted-foreground hidden truncate text-xs sm:block">
              {t('subtitle')}
            </p>
          </div>
        </Link>
        <div className="flex items-center gap-1 sm:gap-2">
          <BackendStatus />
          <Button
            asChild
            size="sm"
            variant={isRepositoriesPage ? 'secondary' : 'ghost'}
          >
            <Link href="/repos">{t('repositories')}</Link>
          </Button>
          <SettingsMenu />
        </div>
      </div>
    </nav>
  );
}
