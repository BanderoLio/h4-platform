import createMiddleware from 'next-intl/middleware';

import { defaultLocale, LOCALES, localePrefix } from './i18n';

export default createMiddleware({
  locales: LOCALES,
  defaultLocale,
  localePrefix,
});

export const config = {
  matcher: ['/((?!api|_next|_vercel|.*\\..*).*)'],
};
