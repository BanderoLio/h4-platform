import { PropsWithChildren } from 'react';
import {
  FormControl,
  FormDescription,
  FormLabel,
  FormMessage,
  FormItem as SFormItem,
} from './ui/form';

type FormItemProps = PropsWithChildren<{
  label?: string;
  description?: string;
}>;

export function FormItem({ label, description, children }: FormItemProps) {
  return (
    <SFormItem>
      {label && <FormLabel>{label}</FormLabel>}
      <FormControl>{children}</FormControl>
      {description && <FormDescription>{description}</FormDescription>}
      <FormMessage />
    </SFormItem>
  );
}
