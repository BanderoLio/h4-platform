import type {
  AgentMessage,
  AgentMessageRole,
  AgentSession,
  RepositoryRecord,
  RepositoryWorkspace,
  WorkspaceStore,
} from './types';

export const REPOSITORIES_STORAGE_KEY = 'security-agent-repositories-v1';
export const WORKSPACES_STORAGE_KEY = 'security-agent-workspaces-v1';

function isBrowser() {
  return typeof window !== 'undefined';
}

function generateId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function readFromStorage<T>(key: string, fallback: T): T {
  if (!isBrowser()) {
    return fallback;
  }

  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }

  try {
    return JSON.parse(raw) as T;
  } catch {
    window.localStorage.removeItem(key);
    return fallback;
  }
}

function writeToStorage<T>(key: string, value: T) {
  if (!isBrowser()) {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(value));
}

export function deriveRepositoryName(url: string) {
  try {
    const parsed = new URL(url.trim());
    const segments = parsed.pathname
      .split('/')
      .map((segment) => segment.trim())
      .filter(Boolean);
    const [owner, repo] = segments;

    if (owner && repo) {
      return `${owner}/${repo.replace(/\.git$/i, '')}`;
    }
    if (repo) {
      return repo.replace(/\.git$/i, '');
    }
  } catch {
    // Ignore invalid URL fallback cases.
  }

  return 'Repository';
}

export function createRepositoryRecord(input: {
  name?: string;
  url: string;
  description?: string;
}): RepositoryRecord {
  const now = new Date().toISOString();
  const name = input.name?.trim() || deriveRepositoryName(input.url);

  return {
    id: generateId(),
    name,
    url: input.url.trim(),
    description: input.description?.trim() || undefined,
    createdAt: now,
    updatedAt: now,
  };
}

export function loadRepositories() {
  return readFromStorage<RepositoryRecord[]>(REPOSITORIES_STORAGE_KEY, []);
}

export function saveRepositories(repositories: RepositoryRecord[]) {
  writeToStorage(REPOSITORIES_STORAGE_KEY, repositories);
}

export function loadWorkspaces() {
  return readFromStorage<WorkspaceStore>(WORKSPACES_STORAGE_KEY, {});
}

export function saveWorkspaces(workspaces: WorkspaceStore) {
  writeToStorage(WORKSPACES_STORAGE_KEY, workspaces);
}

export function createEmptyWorkspace(repoId: string): RepositoryWorkspace {
  return {
    repoId,
    activeSessionId: null,
    sessions: [],
  };
}

export function createAgentSession(title?: string): AgentSession {
  const now = new Date().toISOString();

  return {
    id: generateId(),
    title: title?.trim() || 'New agent run',
    createdAt: now,
    updatedAt: now,
    status: 'idle',
    messages: [],
  };
}

export function createAgentMessage(
  role: AgentMessageRole,
  content: string,
  status: AgentMessage['status'] = 'done',
): AgentMessage {
  return {
    id: generateId(),
    role,
    content,
    createdAt: new Date().toISOString(),
    status,
  };
}
