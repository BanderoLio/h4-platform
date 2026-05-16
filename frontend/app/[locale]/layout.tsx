import type { ReactNode } from 'react';
import { NextIntlClientProvider } from 'next-intl';
import { getMessages, setRequestLocale } from 'next-intl/server';
import { LOCALES } from '@/i18n';
import { ThemeProvider } from '@/shared/providers/theme.provider';
import { QueryProvider } from '@/shared/providers/query.provider';
import { MainLayout } from '@/widgets/layouts/MainLayout';
import { Toaster } from 'sonner';

type LocaleLayoutProps = {
  children: ReactNode;
  params: Promise<{ locale: string }>;
};

export function generateStaticParams() {
  return LOCALES.map((locale) => ({ locale }));
}

export default async function LocaleLayout({
  children,
  params,
}: LocaleLayoutProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const messages = await getMessages({ locale });

  return (
    <NextIntlClientProvider locale={locale} messages={messages}>
      <QueryProvider>
        <ThemeProvider>
          <MainLayout>{children}</MainLayout>
          <Toaster position="top-right" richColors />
        </ThemeProvider>
      </QueryProvider>
    </NextIntlClientProvider>
  );
}
