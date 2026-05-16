import { Inter, Pixelify_Sans, JetBrains_Mono } from 'next/font/google';

export const inter = Inter({
  variable: '--font-inter',
  subsets: ['latin', 'cyrillic'],
  display: 'swap',
  preload: true,
});

export const jetBrainsMono = JetBrains_Mono({
  variable: '--font-jetbrains-mono',
  subsets: ['latin', 'cyrillic'],
  display: 'swap',
  preload: true,
});

export const pixelifySans = Pixelify_Sans({
  variable: '--font-pixelify-sans',
  subsets: ['latin'],
  display: 'swap',
});
