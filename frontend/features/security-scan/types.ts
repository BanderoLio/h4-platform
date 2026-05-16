export type ScanStatus = 'running' | 'awaiting_input' | 'completed' | 'failed';

export type StartScanRequest = {
  repo_url: string;
  interactive?: boolean;
  query?: string;
};

export type StartScanResponse = {
  scan_id: string;
};

export type ScanReportResponse = {
  status: ScanStatus;
  report: string | null;
};

export type ScanNotFoundResponse = {
  detail: string;
};

export type ResumeScanRequest = {
  answer: string;
};

export type ResumeScanResponse = {
  detail?: string;
};

export type ScanSessionListItem = {
  id: string;
  status: ScanStatus;
  repo: string;
  task: string;
  created_at: string;
  updated_at: string;
};

export type ScanSessionListResponse = {
  items: ScanSessionListItem[];
  limit: number;
  offset: number;
};
