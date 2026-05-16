import { RepoWorkspacePage } from '@/views/repo-workspace.page';

type RepoWorkspaceRouteProps = {
  params: Promise<{ repoId: string }>;
};

export default async function RepoWorkspaceRoute({
  params,
}: RepoWorkspaceRouteProps) {
  const { repoId } = await params;

  return <RepoWorkspacePage repoId={repoId} />;
}
