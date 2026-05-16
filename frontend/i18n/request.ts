import { getRequestConfig } from 'next-intl/server';

import { LOCALES, defaultLocale, type TLocale } from '../i18n';

export default getRequestConfig(async ({ locale }) => {
  const currentLocale = LOCALES.includes(locale as TLocale)
    ? (locale as TLocale)
    : defaultLocale;

  const messages = (await import(`../messages/${currentLocale}.json`)).default;

  return {
    locale: currentLocale,
    messages,
  };
});
