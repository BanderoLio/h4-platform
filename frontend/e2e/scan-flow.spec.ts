import { test, expect } from '@playwright/test';

/**
 * Full-flow e2e against the live stack (frontend + BFF proxy + backend).
 *
 * Exercises the real integration path:
 *   - the BFF proxy reaches the backend with the injected API key,
 *   - a scan starts, is polled, and its report renders,
 *   - the backend session is correlated back to the repository by repo_url.
 *
 * The backend runs the agentsec stub with AGENTSEC_STUB_BEHAVIOR=instant_completed
 * (see docker-compose.yml), so scans complete deterministically.
 */

// GitHub's canonical tiny test repository — small, public, always available.
const REPO_URL = 'https://github.com/octocat/Hello-World';
const REPO_NAME = 'octocat/Hello-World';

test.beforeEach(async ({ page }) => {
  // Each test starts from a clean browser-local repository registry.
  await page.goto('/');
  await page.evaluate(() => window.localStorage.clear());
});

test('add a repository, run a scan, and read the report', async ({ page }) => {
  await page.goto('/en/repos');

  // The navbar health poll should report the backend as reachable.
  await expect(page.getByText('Backend online')).toBeVisible();

  // Register a repository.
  await page.getByLabel('Repository URL').fill(REPO_URL);
  await page.getByRole('button', { name: 'Add repository' }).click();

  // It shows up in the saved repositories list (exact match: the URL line
  // and the toast also contain this substring).
  await expect(page.getByText(REPO_NAME, { exact: true })).toBeVisible();

  // Open its workspace.
  await page.getByRole('link', { name: /Open workspace/i }).click();
  await expect(page).toHaveURL(/\/en\/repos\/[^/]+$/);

  // Send a prompt to the security agent.
  const promptText = 'Check this repository for release blockers.';
  await page.getByPlaceholder(/Ask the security agent/i).fill(promptText);
  await page.getByRole('button', { name: 'Send' }).click();

  // The user message appears in the transcript.
  await expect(page.getByText(promptText).first()).toBeVisible();

  // The agent's report renders once the scan completes.
  await expect(page.getByText(/completed for repo/i)).toBeVisible({
    timeout: 60_000,
  });

  // The run is recorded in the per-repository history sidebar.
  await expect(page.getByText('Completed').first()).toBeVisible();
});

test('a registered repository survives a page reload', async ({ page }) => {
  await page.goto('/en/repos');
  await page.getByLabel('Repository URL').fill(REPO_URL);
  await page.getByRole('button', { name: 'Add repository' }).click();
  await expect(page.getByText(REPO_NAME, { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByText(REPO_NAME, { exact: true })).toBeVisible();
});
