'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AxiosError } from 'axios';
import {
  ArrowLeft,
  Bot,
  Clock3,
  LoaderCircle,
  MessageSquarePlus,
  SendHorizontal,
  UserRound,
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Link } from '@/navigation';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { MarkdownContent } from '@/components/markdown-content';
import { ThinkingIndicator } from '@/components/thinking-indicator';
import {
  getScanReport,
  listScanSessions,
  resumeScan,
  startScan,
} from '@/features/security-scan';
import type { ScanReportResponse } from '@/features/security-scan';
import {
  createAgentMessage,
  createEmptyWorkspace,
  loadRepositories,
  loadWorkspaces,
  saveRepositories,
  saveWorkspaces,
} from '@/features/repositories';
import type {
  AgentMessage,
  AgentSession,
  RepositoryWorkspace,
  WorkspaceStore,
} from '@/features/repositories';

const MAX_REPORT_ATTEMPTS = 120;
const REPORT_POLL_INTERVAL_MS = 2500;
const SESSION_SYNC_INTERVAL_MS = 8000;
const SESSION_SYNC_LIMIT = 200;

function sleep(ms: number) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function normalizeRepositoryUrl(url: string) {
  return url.trim().replace(/\/+$/, '').toLowerCase();
}

function sortSessions(sessions: AgentSession[]) {
  return [...sessions].sort(
    (left, right) =>
      new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime(),
  );
}

function upsertSession(sessions: AgentSession[], session: AgentSession) {
  return sortSessions([
    session,
    ...sessions.filter((item) => item.id !== session.id),
  ]);
}

function resolveErrorMessage(
  error: unknown,
  fallbackMessage: string,
  notFoundMessage: string,
) {
  const axiosError = error as AxiosError<{ detail?: string }>;

  if (axiosError.response?.status === 404) {
    return notFoundMessage;
  }
  if (axiosError.response?.data?.detail) {
    return axiosError.response.data.detail;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallbackMessage;
}

async function waitForScanReportState(scanId: string, timeoutMessage: string) {
  for (let attempt = 0; attempt < MAX_REPORT_ATTEMPTS; attempt += 1) {
    const report = await getScanReport(scanId);
    if (report.status !== 'running') {
      return report;
    }
    await sleep(REPORT_POLL_INTERVAL_MS);
  }

  throw new Error(timeoutMessage);
}

function applyReportToPendingMessage(
  messages: AgentMessage[],
  messageId: string,
  content: string,
  status: AgentMessage['status'],
): AgentMessage[] {
  let found = false;

  const updated = messages.map((message) => {
    if (message.id !== messageId) {
      return message;
    }
    found = true;
    return {
      ...message,
      content,
      status,
    };
  });

  if (found) {
    return updated;
  }

  const fallbackMessage: AgentMessage = {
    id: messageId,
    role: 'assistant',
    content,
    createdAt: new Date().toISOString(),
    status,
  };

  return [...messages, fallbackMessage];
}

function resolveReportMessage(
  report: ScanReportResponse,
  emptyDoneReport: string,
  emptyFailedReport: string,
  awaitingInputFallback: string,
) {
  // When the scan pauses, surface the agent's actual question so the user
  // knows what to answer; fall back to a generic prompt only if missing.
  if (report.status === 'awaiting_input') {
    return report.question?.trim() || awaitingInputFallback;
  }
  const reportContent = report.report?.trim();
  if (reportContent) {
    return reportContent;
  }
  if (report.status === 'completed') {
    return emptyDoneReport;
  }
  if (report.status === 'failed') {
    return emptyFailedReport;
  }
  return awaitingInputFallback;
}

type RepoWorkspacePageProps = {
  repoId: string;
};

export function RepoWorkspacePage({ repoId }: RepoWorkspacePageProps) {
  const t = useTranslations('RepoWorkspace');
  const tErrors = useTranslations('Errors');

  const [repositories, setRepositories] = useState(() => loadRepositories());
  const [workspaces, setWorkspaces] = useState<WorkspaceStore>(() =>
    loadWorkspaces(),
  );
  const [prompt, setPrompt] = useState('');
  const [requestError, setRequestError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [isSyncingSessions, setIsSyncingSessions] = useState(false);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);

  const repository = useMemo(
    () => repositories.find((item) => item.id === repoId) ?? null,
    [repositories, repoId],
  );
  const repositoryId = repository?.id ?? null;
  const repositoryUrl = repository?.url ?? null;
  const workspace = useMemo(
    () => workspaces[repoId] ?? createEmptyWorkspace(repoId),
    [repoId, workspaces],
  );
  const activeSession = useMemo(
    () =>
      workspace.sessions.find(
        (session) => session.id === workspace.activeSessionId,
      ) ??
      workspace.sessions[0] ??
      null,
    [workspace],
  );
  const quickPrompts = useMemo(
    () => [t('quickPrompt1'), t('quickPrompt2'), t('quickPrompt3')],
    [t],
  );
  const isAwaitingInput = activeSession?.status === 'awaiting_input';

  const updateWorkspace = useCallback(
    (updater: (current: RepositoryWorkspace) => RepositoryWorkspace) => {
      setWorkspaces((prev) => {
        const current = prev[repoId] ?? createEmptyWorkspace(repoId);
        const updated = updater(current);
        const next = { ...prev, [repoId]: updated };
        saveWorkspaces(next);
        return next;
      });
    },
    [repoId],
  );

  const syncSessionsFromBackend = useCallback(async () => {
    if (!repositoryUrl) {
      return;
    }

    setIsSyncingSessions(true);

    try {
      const sessionList = await listScanSessions({
        limit: SESSION_SYNC_LIMIT,
        offset: 0,
      });
      const targetRepoUrl = normalizeRepositoryUrl(repositoryUrl);
      // Match on the original git URL (repo_url). `item.repo` is the
      // server-side clone path and never equals the registry URL.
      const repoSessions = sessionList.items.filter(
        (item) =>
          !!item.repo_url &&
          normalizeRepositoryUrl(item.repo_url) === targetRepoUrl,
      );

      updateWorkspace((current) => {
        const currentById = new Map(
          current.sessions.map((session) => [session.id, session]),
        );
        const backendIds = new Set(repoSessions.map((session) => session.id));

        const mergedFromBackend: AgentSession[] = repoSessions.map(
          (session) => {
            const existing = currentById.get(session.id);
            const hasUserMessage =
              existing?.messages.some((message) => message.role === 'user') ??
              false;
            const bootstrappedMessages =
              hasUserMessage || !session.task
                ? (existing?.messages ?? [])
                : [
                    createAgentMessage('user', session.task, 'done'),
                    ...(existing?.messages ?? []),
                  ];

            return {
              id: session.id,
              title:
                existing?.title ||
                session.task?.slice(0, 80) ||
                t('newSessionTitle'),
              createdAt: existing?.createdAt || session.created_at,
              updatedAt: session.updated_at,
              status: session.status,
              lastScanId: session.id,
              messages: bootstrappedMessages,
            };
          },
        );

        const localOnly = current.sessions.filter(
          (session) => !backendIds.has(session.id),
        );
        const sessions = sortSessions([...mergedFromBackend, ...localOnly]);

        const nextActiveSessionId =
          current.activeSessionId &&
          sessions.some((session) => session.id === current.activeSessionId)
            ? current.activeSessionId
            : (sessions[0]?.id ?? null);

        return {
          ...current,
          activeSessionId: nextActiveSessionId,
          sessions,
        };
      });
    } catch {
      // Keep UI usable with local state if list endpoint fails temporarily.
    } finally {
      setIsSyncingSessions(false);
    }
  }, [repositoryUrl, t, updateWorkspace]);

  const finalizeAssistantMessage = useCallback(
    (
      sessionId: string,
      pendingMessageId: string,
      report: ScanReportResponse,
    ) => {
      updateWorkspace((current) => {
        const session = current.sessions.find((item) => item.id === sessionId);
        if (!session) {
          return current;
        }

        const content = resolveReportMessage(
          report,
          t('emptyDoneReport'),
          t('emptyFailedReport'),
          t('awaitingInputDefault'),
        );
        const messageStatus =
          report.status === 'failed'
            ? 'error'
            : report.status === 'running'
              ? 'pending'
              : 'done';
        const updatedSession: AgentSession = {
          ...session,
          status: report.status,
          updatedAt: new Date().toISOString(),
          messages: applyReportToPendingMessage(
            session.messages,
            pendingMessageId,
            content,
            messageStatus,
          ),
        };

        return {
          ...current,
          sessions: upsertSession(current.sessions, updatedSession),
        };
      });
    },
    [t, updateWorkspace],
  );

  const markPendingMessageAsError = useCallback(
    (sessionId: string, pendingMessageId: string, message: string) => {
      updateWorkspace((current) => {
        const session = current.sessions.find((item) => item.id === sessionId);
        if (!session) {
          return current;
        }

        const updatedSession: AgentSession = {
          ...session,
          status: 'failed',
          updatedAt: new Date().toISOString(),
          messages: applyReportToPendingMessage(
            session.messages,
            pendingMessageId,
            `${t('assistantFailedPrefix')}\n\n${message}`,
            'error',
          ),
        };

        return {
          ...current,
          sessions: upsertSession(current.sessions, updatedSession),
        };
      });
    },
    [t, updateWorkspace],
  );

  useEffect(() => {
    if (!chatContainerRef.current) {
      return;
    }
    chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
  }, [activeSession?.id, activeSession?.messages.length]);

  useEffect(() => {
    if (!repositoryId) {
      return;
    }

    const now = new Date().toISOString();
    setRepositories((prev) => {
      const next = prev.map((item) =>
        item.id === repoId
          ? { ...item, lastOpenedAt: now, updatedAt: now }
          : item,
      );
      saveRepositories(next);
      return next;
    });
  }, [repoId, repositoryId]);

  useEffect(() => {
    if (!repositoryId) {
      return;
    }

    void syncSessionsFromBackend();

    const intervalId = window.setInterval(() => {
      void syncSessionsFromBackend();
    }, SESSION_SYNC_INTERVAL_MS);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [repositoryId, syncSessionsFromBackend]);

  const selectSession = (sessionId: string) => {
    updateWorkspace((current) => ({
      ...current,
      activeSessionId: sessionId,
    }));
    setRequestError(null);
  };

  const createNewRun = () => {
    updateWorkspace((current) => ({
      ...current,
      activeSessionId: null,
    }));
    setPrompt('');
    setRequestError(null);
  };

  const submitPrompt = async () => {
    if (!repositoryUrl || isSending) {
      return;
    }

    const promptText = prompt.trim();
    if (!promptText) {
      setRequestError(t('promptRequired'));
      return;
    }

    setPrompt('');
    setRequestError(null);
    setIsSending(true);

    const userMessage = createAgentMessage('user', promptText, 'done');
    const pendingAssistantMessage = createAgentMessage(
      'assistant',
      t('assistantThinking'),
      'pending',
    );

    if (isAwaitingInput && activeSession?.id) {
      const sessionId = activeSession.id;
      const scanId = activeSession.lastScanId || activeSession.id;

      updateWorkspace((current) => {
        const session = current.sessions.find((item) => item.id === sessionId);
        if (!session) {
          return current;
        }

        const updatedSession: AgentSession = {
          ...session,
          status: 'running',
          updatedAt: new Date().toISOString(),
          messages: [...session.messages, userMessage, pendingAssistantMessage],
        };

        return {
          ...current,
          sessions: upsertSession(current.sessions, updatedSession),
        };
      });

      try {
        await resumeScan(scanId, { answer: promptText });
        const report = await waitForScanReportState(scanId, t('reportTimeout'));
        finalizeAssistantMessage(sessionId, pendingAssistantMessage.id, report);
        await syncSessionsFromBackend();
      } catch (error) {
        const message = resolveErrorMessage(
          error,
          tErrors('default'),
          t('scanNotFound'),
        );
        setRequestError(message);
        markPendingMessageAsError(
          sessionId,
          pendingAssistantMessage.id,
          message,
        );
        await syncSessionsFromBackend();
      } finally {
        setIsSending(false);
      }
      return;
    }

    // Render the user message and a "thinking" placeholder immediately —
    // before POST /scan/start resolves — so the chat reflects the request
    // with no dead window. The scan id is unknown until the backend
    // answers, so the session starts under a temporary id and is swapped
    // for the real one once /scan/start returns.
    const placeholderSessionId = `pending-${pendingAssistantMessage.id}`;
    const startedAt = new Date().toISOString();
    const placeholderSession: AgentSession = {
      id: placeholderSessionId,
      title: promptText.slice(0, 80),
      createdAt: startedAt,
      updatedAt: startedAt,
      status: 'running',
      messages: [userMessage, pendingAssistantMessage],
    };

    updateWorkspace((current) => ({
      ...current,
      activeSessionId: placeholderSessionId,
      sessions: upsertSession(current.sessions, placeholderSession),
    }));

    // Tracks the session the pending message currently lives under, so an
    // error can be attached whether it fails before or after the id swap.
    let pendingSessionId = placeholderSessionId;

    try {
      const { scan_id: scanId } = await startScan({
        repo_url: repositoryUrl,
        interactive: true,
        query: promptText,
      });

      // Swap the temporary id for the real scan id, keeping the transcript.
      updateWorkspace((current) => {
        const placeholder =
          current.sessions.find((item) => item.id === placeholderSessionId) ??
          placeholderSession;
        const startedSession: AgentSession = {
          ...placeholder,
          id: scanId,
          lastScanId: scanId,
          updatedAt: new Date().toISOString(),
        };
        const withoutPlaceholder = current.sessions.filter(
          (item) => item.id !== placeholderSessionId,
        );
        return {
          ...current,
          activeSessionId: scanId,
          sessions: upsertSession(withoutPlaceholder, startedSession),
        };
      });
      pendingSessionId = scanId;

      const report = await waitForScanReportState(scanId, t('reportTimeout'));
      finalizeAssistantMessage(scanId, pendingAssistantMessage.id, report);
      await syncSessionsFromBackend();
    } catch (error) {
      const message = resolveErrorMessage(
        error,
        tErrors('default'),
        t('scanNotFound'),
      );
      setRequestError(message);
      // Surface the failure inside the chat too, not only as a banner.
      markPendingMessageAsError(
        pendingSessionId,
        pendingAssistantMessage.id,
        message,
      );
    } finally {
      setIsSending(false);
    }
  };

  if (!repository) {
    return (
      <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 sm:py-10">
        <Alert variant="destructive">
          <AlertTitle>{t('repositoryNotFoundTitle')}</AlertTitle>
          <AlertDescription>
            {t('repositoryNotFoundDescription')}
          </AlertDescription>
        </Alert>
        <Button asChild className="mt-4">
          <Link href="/repos">
            <ArrowLeft className="h-4 w-4" />
            {t('backToRepositories')}
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="h-full px-4 py-5 sm:px-6">
      <div className="grid h-full min-h-[calc(100dvh-12rem)] gap-3 lg:grid-cols-[280px_1fr]">
        <aside className="bg-card flex h-full min-h-72 flex-col rounded-xl border p-3">
          <div className="mb-3 border-b pb-3">
            <p className="text-sm font-semibold">{repository.name}</p>
            <p className="text-muted-foreground mt-1 line-clamp-2 text-xs">
              {repository.url}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3 w-full"
              onClick={createNewRun}
            >
              <MessageSquarePlus className="h-4 w-4" />
              {t('newSessionAction')}
            </Button>
          </div>

          <div className="text-muted-foreground mb-2 inline-flex items-center gap-2 text-[11px]">
            {isSyncingSessions && (
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            )}
            {t('sessionSyncLabel')}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {workspace.sessions.length === 0 ? (
              <p className="text-muted-foreground text-xs">
                {t('sessionHistoryEmpty')}
              </p>
            ) : (
              <ul className="space-y-2">
                {workspace.sessions.map((session) => (
                  <li key={session.id}>
                    <button
                      type="button"
                      className={cn(
                        'w-full rounded-lg border p-2 text-left transition-colors',
                        session.id === activeSession?.id
                          ? 'border-primary bg-primary/5'
                          : 'hover:bg-muted/50',
                      )}
                      onClick={() => selectSession(session.id)}
                    >
                      <p className="line-clamp-2 text-xs font-medium sm:text-sm">
                        {session.title}
                      </p>
                      <div className="text-muted-foreground mt-2 flex items-center gap-2 text-[11px]">
                        <Clock3 className="h-3 w-3" />
                        {new Date(session.updatedAt).toLocaleString()}
                      </div>
                      <p className="text-muted-foreground mt-1 text-[11px]">
                        {t(
                          `status.${session.status === 'done' ? 'completed' : session.status}`,
                        )}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <section className="bg-card flex h-full min-h-112 flex-col rounded-xl border">
          <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">
                {activeSession?.title || t('newSessionTitle')}
              </p>
              <p className="text-muted-foreground truncate text-xs">
                {repository.url}
              </p>
            </div>
            <Button asChild size="sm" variant="ghost">
              <Link href="/repos">
                <ArrowLeft className="h-4 w-4" />
                {t('backToRepositories')}
              </Link>
            </Button>
          </header>

          <div
            ref={chatContainerRef}
            className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4"
          >
            {!activeSession || activeSession.messages.length === 0 ? (
              <div className="space-y-3 rounded-xl border border-dashed p-4">
                <p className="text-sm font-medium">{t('emptyStateTitle')}</p>
                <p className="text-muted-foreground text-sm">
                  {t('emptyStateDescription')}
                </p>
                <div className="flex flex-wrap gap-2">
                  {quickPrompts.map((quickPrompt) => (
                    <Button
                      key={quickPrompt}
                      size="sm"
                      variant="outline"
                      onClick={() => setPrompt(quickPrompt)}
                    >
                      {quickPrompt}
                    </Button>
                  ))}
                </div>
              </div>
            ) : (
              activeSession.messages.map((message) => (
                <article
                  key={message.id}
                  className={cn(
                    'max-w-3xl rounded-xl border px-3 py-2 sm:px-4 sm:py-3',
                    message.role === 'user'
                      ? 'bg-primary/5 ml-auto'
                      : 'bg-muted/40 mr-auto',
                  )}
                >
                  <div className="text-muted-foreground mb-2 flex items-center gap-2 text-xs">
                    {message.role === 'user' ? (
                      <UserRound className="h-3.5 w-3.5" />
                    ) : (
                      <Bot className="h-3.5 w-3.5" />
                    )}
                    <span>
                      {message.role === 'user'
                        ? t('youLabel')
                        : t('assistantLabel')}
                    </span>
                    {message.status === 'pending' && (
                      <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                    )}
                  </div>

                  {message.role === 'assistant' ? (
                    message.status === 'pending' ? (
                      <ThinkingIndicator label={message.content} />
                    ) : (
                      <MarkdownContent
                        content={message.content}
                        className={cn(
                          message.status === 'error' && 'text-destructive',
                        )}
                      />
                    )
                  ) : (
                    <p className="text-sm whitespace-pre-wrap">
                      {message.content}
                    </p>
                  )}
                </article>
              ))
            )}
          </div>

          <div className="space-y-3 border-t px-4 py-3">
            {isAwaitingInput && (
              <Alert>
                <AlertTitle>{t('awaitingInputTitle')}</AlertTitle>
                <AlertDescription>
                  {t('awaitingInputDescription')}
                </AlertDescription>
              </Alert>
            )}

            {requestError && (
              <Alert variant="destructive">
                <AlertTitle>{t('requestErrorTitle')}</AlertTitle>
                <AlertDescription>{requestError}</AlertDescription>
              </Alert>
            )}

            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void submitPrompt();
              }}
            >
              <Textarea
                rows={3}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder={
                  isAwaitingInput
                    ? t('resumePlaceholder')
                    : t('promptPlaceholder')
                }
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    void submitPrompt();
                  }
                }}
              />
              <Button type="submit" disabled={isSending}>
                {isSending ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <SendHorizontal className="h-4 w-4" />
                )}
                {isAwaitingInput ? t('resumeAction') : t('sendAction')}
              </Button>
            </form>
          </div>
        </section>
      </div>
    </div>
  );
}
