import type { ComponentProps, PropsWithChildren } from 'react';
import { Button } from './ui/button';
import { AccessibleIcon } from '@radix-ui/react-accessible-icon';
import { TextTooltip } from './tooltip';

type IconButtonProps = PropsWithChildren<
  ComponentProps<typeof Button> & {
    label: string;
    tooltip?: boolean;
  }
>;

export function IconButton({
  label,
  children,
  tooltip = true,
  ...props
}: IconButtonProps) {
  if (!tooltip) {
    return (
      <Button {...props}>
        <AccessibleIcon label={label}>{children}</AccessibleIcon>
      </Button>
    );
  }
  return (
    <TextTooltip label={label}>
      <Button {...props}>
        <AccessibleIcon label={''}>{children}</AccessibleIcon>
      </Button>
    </TextTooltip>
  );
}
