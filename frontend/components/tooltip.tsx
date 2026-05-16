'use client';

import { PropsWithChildren } from 'react';
import {
  Tooltip as STooltip,
  TooltipContent,
  TooltipTrigger,
} from './ui/tooltip';

export function TextTooltip({
  children,
  label,
}: PropsWithChildren<{ label: string }>) {
  return (
    <STooltip delayDuration={550}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>
        <p>{label}</p>
      </TooltipContent>
    </STooltip>
  );
}
