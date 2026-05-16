import type { AxiosError } from 'axios';
import { useQuery } from '@tanstack/react-query';
import { getScanReport } from '../security-scan.api';
import type { ScanStatus } from '../types';

const STOP_POLL_STATUSES: ScanStatus[] = [
  'awaiting_input',
  'completed',
  'failed',
];
const POLL_INTERVAL_MS = 2500;

export function useScanReport(scanId: string | null) {
  return useQuery({
    queryKey: ['scan-report', scanId],
    queryFn: () => getScanReport(scanId ?? ''),
    enabled: Boolean(scanId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || STOP_POLL_STATUSES.includes(status)) {
        return false;
      }
      return POLL_INTERVAL_MS;
    },
    retry: (failureCount, error) => {
      const axiosError = error as AxiosError;

      if (axiosError.response?.status === 404) {
        return false;
      }
      return failureCount < 2;
    },
  });
}
