export type ScanStatus = 'running' | 'awaiting_input' | 'completed' | 'failed';

export type StartScanRequest = {
  repo_url: string;
  interactive?: boolean;
  query?: string;
};

export type StartScanResponse = {
  scan_id: string;
};

export type ScanInterruptType = 'clarify' | 'gate';

export type ScanReportResponse = {
  status: ScanStatus;
  report: string | null;
  // Present only while status is 'awaiting_input': the kind of pause and the
  // agent's question to show the user before they call /resume.
  interrupt_type?: ScanInterruptType | null;
  question?: string | null;
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
  // Server-side path to the cloned repository — not a stable identity key.
  repo: string;
  // Original git URL the scan was started from. This is what the frontend
  // correlates against its local repository registry. Null for local-path
  // scans started via repo_path.
  repo_url: string | null;
  task: string;
  created_at: string;
  updated_at: string;
};

export type ScanSessionListResponse = {
  items: ScanSessionListItem[];
  limit: number;
  offset: number;
};
