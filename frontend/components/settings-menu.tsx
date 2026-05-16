'use client';

import { useState } from 'react';
import { Settings, Moon, Sun, Globe, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useTheme } from 'next-themes';
import { useTranslations, useLocale } from 'next-intl';
import { usePathname, useRouter } from '@/navigation';
import { LOCALES } from '@/i18n';
import { useMounted } from '@/hooks/use-mounted';
import { cn } from '@/lib/utils';

export function SettingsMenu() {
  const [isOpen, setIsOpen] = useState(false);
  const { theme, setTheme, resolvedTheme } = useTheme();
  const mounted = useMounted();
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations('Settings');
  const tLocale = useTranslations('LocaleSwitcher');

  const isDark = resolvedTheme === 'dark' || theme === 'dark';

  const handleLocaleChange = (targetLocale: string) => {
    if (targetLocale === locale) {
      setIsOpen(false);
      return;
    }
    const basePath =
      pathname && LOCALES.some((loc) => pathname.startsWith(`/${loc}`))
        ? pathname.replace(/^\/(en|ru)(?=\/|$)/, '') || '/'
        : pathname || '/';

    router.replace(basePath, { locale: targetLocale });
    setIsOpen(false);
  };

  const handleThemeChange = (newTheme: 'light' | 'dark') => {
    setTheme(newTheme);
    setIsOpen(false);
  };

  if (!mounted) {
    return (
      <Button
        variant="ghost"
        size="icon"
        className="h-9 w-9"
        aria-label={t('menuLabel')}
        disabled
      >
        <Settings className="h-4 w-4" aria-hidden="true" />
      </Button>
    );
  }

  return (
    <Popover open={isOpen} onOpenChange={setIsOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9"
          aria-label={t('menuLabel')}
        >
          <Settings className="h-4 w-4" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-56 p-2">
        <div className="mb-2">
          <div className="text-muted-foreground mb-1.5 px-2 text-xs font-medium">
            {t('theme')}
          </div>
          <button
            onClick={() => handleThemeChange('light')}
            className={cn(
              'hover:bg-accent hover:text-accent-foreground flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm',
              !isDark && 'bg-accent text-accent-foreground',
            )}
            role="menuitem"
          >
            <div className="flex items-center gap-2">
              <Sun className="h-4 w-4" />
              <span>{t('light')}</span>
            </div>
            {!isDark && <Check className="h-4 w-4" />}
          </button>
          <button
            onClick={() => handleThemeChange('dark')}
            className={cn(
              'hover:bg-accent hover:text-accent-foreground flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm',
              isDark && 'bg-accent text-accent-foreground',
            )}
            role="menuitem"
          >
            <div className="flex items-center gap-2">
              <Moon className="h-4 w-4" />
              <span>{t('dark')}</span>
            </div>
            {isDark && <Check className="h-4 w-4" />}
          </button>
        </div>

        <div className="bg-border my-2 h-px" />

        <div>
          <div className="text-muted-foreground mb-1.5 px-2 text-xs font-medium">
            {t('language')}
          </div>
          {LOCALES.map((itemLocale: string) => (
            <button
              key={itemLocale}
              onClick={() => handleLocaleChange(itemLocale)}
              className={cn(
                'hover:bg-accent hover:text-accent-foreground flex w-full items-center justify-between rounded-sm px-2 py-1.5 text-sm',
                locale === itemLocale && 'bg-accent text-accent-foreground',
              )}
              role="menuitem"
            >
              <div className="flex items-center gap-2">
                <Globe className="h-4 w-4" />
                <span>{tLocale(itemLocale)}</span>
              </div>
              {locale === itemLocale && <Check className="h-4 w-4" />}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
