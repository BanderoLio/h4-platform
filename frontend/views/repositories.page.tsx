'use client';

import { useEffect, useMemo, useState } from 'react';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import {
  ArrowRight,
  FolderGit2,
  Plus,
  Trash2,
  Clock3,
  Boxes,
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Link } from '@/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  createRepositoryRecord,
  loadRepositories,
  loadWorkspaces,
  saveRepositories,
  saveWorkspaces,
} from '@/features/repositories';
import { listScanSessions } from '@/features/security-scan';
import type { RepositoryRecord, WorkspaceStore } from '@/features/repositories';

function normalizeRepositoryUrl(url: string) {
  return url.trim().replace(/\/+$/, '');
}

export function RepositoriesPage() {
  const t = useTranslations('RepositoriesPage');

  const [repositories, setRepositories] = useState<RepositoryRecord[]>(() =>
    loadRepositories(),
  );
  const [workspaces, setWorkspaces] = useState<WorkspaceStore>(() =>
    loadWorkspaces(),
  );
  const [sessionCountsByRepoUrl, setSessionCountsByRepoUrl] = useState<
    Record<string, number>
  >({});
  const [isSyncingSessionCounts, setIsSyncingSessionCounts] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const repositoryFormSchema = useMemo(
    () =>
      z.object({
        url: z.string().trim().url(t('validation.url')),
        name: z.string().trim().max(80, t('validation.nameTooLong')).optional(),
        description: z
          .string()
          .trim()
          .max(200, t('validation.descriptionTooLong'))
          .optional(),
      }),
    [t],
  );

  type RepositoryFormValues = z.infer<typeof repositoryFormSchema>;

  const form = useForm<RepositoryFormValues>({
    resolver: zodResolver(repositoryFormSchema),
    defaultValues: {
      url: '',
      name: '',
      description: '',
    },
  });

  const sortedRepositories = useMemo(
    () =>
      [...repositories].sort((a, b) => {
        const left = a.lastOpenedAt || a.updatedAt || a.createdAt;
        const right = b.lastOpenedAt || b.updatedAt || b.createdAt;
        return new Date(right).getTime() - new Date(left).getTime();
      }),
    [repositories],
  );

  useEffect(() => {
    let isCancelled = false;

    const syncSessionCounts = async () => {
      setIsSyncingSessionCounts(true);

      try {
        const sessions = await listScanSessions({ limit: 200, offset: 0 });
        if (isCancelled) {
          return;
        }

        const nextCounts = sessions.items.reduce<Record<string, number>>(
          (accumulator, session) => {
            const key = normalizeRepositoryUrl(session.repo);
            accumulator[key] = (accumulator[key] ?? 0) + 1;
            return accumulator;
          },
          {},
        );

        setSessionCountsByRepoUrl(nextCounts);
      } catch {
        // Keep repository management usable even if session list endpoint is unavailable.
      } finally {
        if (!isCancelled) {
          setIsSyncingSessionCounts(false);
        }
      }
    };

    void syncSessionCounts();
    const intervalId = window.setInterval(() => {
      void syncSessionCounts();
    }, 10000);

    return () => {
      isCancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  const onSubmit = form.handleSubmit((values) => {
    const normalizedUrl = normalizeRepositoryUrl(values.url);
    const hasDuplicate = repositories.some(
      (repo) =>
        normalizeRepositoryUrl(repo.url).toLowerCase() ===
        normalizedUrl.toLowerCase(),
    );

    if (hasDuplicate) {
      setFormError(t('errors.duplicateUrl'));
      return;
    }

    const record = createRepositoryRecord({
      name: values.name,
      url: normalizedUrl,
      description: values.description,
    });

    const nextRepositories = [record, ...repositories];
    setRepositories(nextRepositories);
    saveRepositories(nextRepositories);
    setFormError(null);
    form.reset();
    toast.success(t('toasts.added', { name: record.name }));
  });

  const markRepositoryOpened = (repoId: string) => {
    const now = new Date().toISOString();
    const nextRepositories = repositories.map((repo) =>
      repo.id === repoId
        ? { ...repo, lastOpenedAt: now, updatedAt: now }
        : repo,
    );

    setRepositories(nextRepositories);
    saveRepositories(nextRepositories);
  };

  const removeRepository = (repoId: string) => {
    const repository = repositories.find((repo) => repo.id === repoId);
    if (!repository) {
      return;
    }

    const confirmed = window.confirm(
      t('deleteConfirm', { name: repository.name }),
    );
    if (!confirmed) {
      return;
    }

    const nextRepositories = repositories.filter((repo) => repo.id !== repoId);
    const nextWorkspaces = { ...workspaces };
    delete nextWorkspaces[repoId];

    setRepositories(nextRepositories);
    setWorkspaces(nextWorkspaces);
    saveRepositories(nextRepositories);
    saveWorkspaces(nextWorkspaces);
    toast.success(t('toasts.deleted', { name: repository.name }));
  };

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <section className="mb-6 space-y-2">
        <p className="text-primary text-sm font-medium">{t('eyebrow')}</p>
        <h1 className="text-2xl font-semibold sm:text-3xl">{t('title')}</h1>
        <p className="text-muted-foreground max-w-3xl text-sm sm:text-base">
          {t('subtitle')}
        </p>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <section className="bg-card space-y-4 rounded-xl border p-4 shadow-sm sm:p-6">
          <div className="flex items-center gap-2">
            <Plus className="text-primary h-4 w-4" />
            <h2 className="text-sm font-semibold sm:text-base">
              {t('formTitle')}
            </h2>
          </div>

          <Form {...form}>
            <form className="space-y-4" onSubmit={onSubmit} noValidate>
              <FormField
                control={form.control}
                name="url"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('urlLabel')}</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t('urlPlaceholder')}
                        autoComplete="off"
                        {...field}
                      />
                    </FormControl>
                    <FormDescription>{t('urlHint')}</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('nameLabel')}</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={t('namePlaceholder')}
                        autoComplete="off"
                        {...field}
                        value={field.value ?? ''}
                      />
                    </FormControl>
                    <FormDescription>{t('nameHint')}</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t('descriptionLabel')}</FormLabel>
                    <FormControl>
                      <Textarea
                        rows={4}
                        placeholder={t('descriptionPlaceholder')}
                        {...field}
                        value={field.value ?? ''}
                      />
                    </FormControl>
                    <FormDescription>{t('descriptionHint')}</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {formError && (
                <Alert variant="destructive">
                  <AlertTitle>{t('formErrorTitle')}</AlertTitle>
                  <AlertDescription>{formError}</AlertDescription>
                </Alert>
              )}

              <Button type="submit" className="w-full sm:w-auto">
                <Plus className="h-4 w-4" />
                {t('addAction')}
              </Button>
            </form>
          </Form>
        </section>

        <section className="bg-card rounded-xl border p-4 shadow-sm sm:p-6">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <FolderGit2 className="text-primary h-4 w-4" />
              <h2 className="text-sm font-semibold sm:text-base">
                {t('listTitle')}
              </h2>
            </div>
            <span className="text-muted-foreground text-xs sm:text-sm">
              {isSyncingSessionCounts
                ? t('countSyncing')
                : t('count', { count: repositories.length })}
            </span>
          </div>

          {sortedRepositories.length === 0 ? (
            <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-sm">
              {t('empty')}
            </p>
          ) : (
            <ul className="space-y-3">
              {sortedRepositories.map((repo) => (
                <li key={repo.id} className="rounded-lg border p-3">
                  <p className="truncate text-sm font-semibold sm:text-base">
                    {repo.name}
                  </p>
                  <p className="text-muted-foreground mt-1 text-xs break-all sm:text-sm">
                    {repo.url}
                  </p>
                  {repo.description && (
                    <p className="text-muted-foreground mt-2 text-xs sm:text-sm">
                      {repo.description}
                    </p>
                  )}
                  <div className="text-muted-foreground mt-3 flex flex-wrap items-center gap-3 text-xs">
                    <span className="inline-flex items-center gap-1">
                      <Boxes className="h-3.5 w-3.5" />
                      {t('sessions', {
                        count:
                          sessionCountsByRepoUrl[
                            normalizeRepositoryUrl(repo.url)
                          ] ?? 0,
                      })}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Clock3 className="h-3.5 w-3.5" />
                      {repo.lastOpenedAt
                        ? t('lastOpened', {
                            date: new Date(repo.lastOpenedAt).toLocaleString(),
                          })
                        : t('neverOpened')}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button
                      asChild
                      size="sm"
                      onClick={() => markRepositoryOpened(repo.id)}
                    >
                      <Link href={`/repos/${repo.id}`}>
                        {t('openWorkspace')}
                        <ArrowRight className="h-4 w-4" />
                      </Link>
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => removeRepository(repo.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                      {t('deleteAction')}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
