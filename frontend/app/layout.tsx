import type { Metadata } from 'next';
import { getLocale } from 'next-intl/server';
import './globals.css';
import { inter, jetBrainsMono, pixelifySans } from './(fonts)/fonts';

export const metadata: Metadata = {
  title: 'Security Agent WebUI',
  description: 'Web interface for repository cybersecurity scanning',
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();

  return (
    <html lang={locale} suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetBrainsMono.variable} ${pixelifySans.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
