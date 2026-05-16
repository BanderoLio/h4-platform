import { getRequestConfig } from 'next-intl/server';

export type TLocale = 'en' | 'ru';
export const LOCALES: TLocale[] = ['en', 'ru'] as const;
export const defaultLocale: TLocale = 'en';
export const localePrefix = 'always' as const;

export default getRequestConfig(async ({ locale }) => {
  const currentLocale = LOCALES.includes(locale as TLocale)
    ? (locale as TLocale)
    : defaultLocale;

  const messages = (await import(`./messages/${currentLocale}.json`)).default;

  return {
    locale: currentLocale,
    messages,
  };
});
