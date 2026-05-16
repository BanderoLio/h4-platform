export type RepositoryRecord = {
  id: string;
  name: string;
  url: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
  lastOpenedAt?: string;
};

export type AgentMessageRole = 'user' | 'assistant';
export type AgentMessageStatus = 'done' | 'pending' | 'error';

export type AgentMessage = {
  id: string;
  role: AgentMessageRole;
  content: string;
  createdAt: string;
  status: AgentMessageStatus;
};

export type AgentSessionStatus =
  | 'idle'
  | 'running'
  | 'awaiting_input'
  | 'completed'
  | 'failed'
  | 'done';

export type AgentSession = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  status: AgentSessionStatus;
  lastScanId?: string;
  messages: AgentMessage[];
};

export type RepositoryWorkspace = {
  repoId: string;
  activeSessionId: string | null;
  sessions: AgentSession[];
};

export type WorkspaceStore = Record<string, RepositoryWorkspace>;
