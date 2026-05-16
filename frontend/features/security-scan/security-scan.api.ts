import { apiClient } from '@/lib/api-client';
import type { Endpoint } from '@/lib/types';
import { createSearchParams } from '@/lib/create-search-params';
import type {
  ScanReportResponse,
  ScanSessionListResponse,
  ResumeScanRequest,
  ResumeScanResponse,
  StartScanRequest,
  StartScanResponse,
} from './types';

const START_SCAN_ENDPOINT: Endpoint<'/scan/start'> = '/scan/start';
const SCAN_SESSIONS_ENDPOINT: Endpoint<'/scan/sessions'> = '/scan/sessions';

export async function startScan(payload: StartScanRequest) {
  const response = await apiClient.post<
    StartScanResponse,
    '/scan/start',
    StartScanRequest
  >(START_SCAN_ENDPOINT, payload);

  return response.data;
}

export async function getScanReport(scanId: string) {
  const endpoint: Endpoint<`/scan/${string}/report`> = `/scan/${scanId}/report`;
  const response = await apiClient.get<
    ScanReportResponse,
    `/scan/${string}/report`
  >(endpoint);

  return response.data;
}

export async function resumeScan(scanId: string, payload: ResumeScanRequest) {
  const endpoint: Endpoint<`/scan/${string}/resume`> = `/scan/${scanId}/resume`;
  const response = await apiClient.post<
    ResumeScanResponse,
    `/scan/${string}/resume`,
    ResumeScanRequest
  >(endpoint, payload);

  return response.data;
}

export async function listScanSessions(
  options: { limit?: number; offset?: number } = {},
) {
  const params = createSearchParams({
    limit: options.limit ?? 50,
    offset: options.offset ?? 0,
  });
  const response = await apiClient.get<
    ScanSessionListResponse,
    '/scan/sessions'
  >(SCAN_SESSIONS_ENDPOINT, params);

  return response.data;
}
