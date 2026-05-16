import { createNavigation } from 'next-intl/navigation';

import { LOCALES, localePrefix } from './i18n';

export const { Link, redirect, usePathname, useRouter } = createNavigation({
  locales: LOCALES,
  localePrefix,
});
