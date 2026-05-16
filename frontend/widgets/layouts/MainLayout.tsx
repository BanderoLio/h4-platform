import { Navbar } from '@/widgets/navbar/navbar';
import type { ReactNode } from 'react';
import { pixelifySans } from '@/app/(fonts)/fonts';

export function MainLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-dvh w-full max-w-full grid-rows-[auto_1fr] overflow-x-hidden">
      <Navbar titleFont={pixelifySans.className} />
      <main className="w-full max-w-full min-w-0">{children}</main>
    </div>
  );
}
