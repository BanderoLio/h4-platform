import { useMutation } from '@tanstack/react-query';
import { startScan } from '../security-scan.api';

export function useStartScan() {
  return useMutation({
    mutationFn: startScan,
  });
}
