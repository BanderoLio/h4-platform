import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./i18n.ts');

const output_mode = process.env.NEXT_OUTPUT;
if (output_mode && output_mode !== 'standalone' && output_mode !== 'export') {
  throw new Error(
    'NEXT_OUTPUT wrong value: only standalone and export are supported',
  );
}

const nextConfig: NextConfig = {
  output: output_mode as 'standalone' | 'export' | undefined,
};

export default withNextIntl(nextConfig);
