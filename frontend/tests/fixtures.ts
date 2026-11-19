import { test as base, expect, type Page, type APIRequestContext } from '@playwright/test'
export type { Page } from '@playwright/test'
export { expect }

/** Follow the visible module navigation without reloading the scientific workspace. */
export async function navigate(page: Page, path: string) {
  const modules: Record<string, string> = {
    '/samples': '/cell-extraction',
    '/raw': '/cell-extraction',
    '/extraction': '/cell-extraction',
    '/preprocess': '/statistics',
    '/data-check': '/statistics',
    '/data-editor': '/statistics',
    '/analysis': '/statistics',
    '/ions': '/annotation',
    '/annotation/evidence': '/annotation',
  }
  const sidebar = page.getByRole('navigation', { name: '工作流程', exact: true })
  const roots: Record<string, string> = {
    '/cell-extraction': '细胞提取',
    '/annotation': '特征注释',
    '/statistics': '统计分析',
  }
  const root = modules[path.split('?')[0]!] ?? path
  const toggle = sidebar.getByRole('button', { name: roots[root], exact: true })
  const destination = sidebar.locator(`a[href="${path.split('?')[0]}"]`).first()
  await expect(async () => {
    if (
      roots[root] &&
      (await toggle.count()) &&
      (await toggle.getAttribute('aria-expanded')) !== 'true'
    )
      await toggle.click()
    await expect(destination).toBeVisible({ timeout: 500 })
  }).toPass({ timeout: 10_000, intervals: [100, 250] })
  await destination.click()
  await expect.poll(() => new URL(page.url()).pathname).toBe(path.split('?')[0])
  if (path.startsWith('/preprocess'))
    await expect(
      page.getByRole('heading', { name: /^(预处理|尚未建立当前数据集|当前输入为独立特征表)$/ }),
    ).toBeVisible()
  const step = new URLSearchParams(path.split('?')[1]).get('step')
  if (
    step &&
    path.startsWith('/preprocess') &&
    (await page.getByLabel('下一项操作', { exact: true }).count())
  )
    await page.getByLabel('下一项操作', { exact: true }).selectOption(step)
}

export async function closeDocument(page: Page) {
  if (page.isClosed() || page.url() === 'about:blank') return
  const closed = page
    .waitForResponse(
      (r) =>
        /\/presence\/(heartbeat|register)$/.test(r.url()) &&
        r.request().method() === 'POST' &&
        r.request().postDataJSON()?.closed,
      { timeout: 2000 },
    )
    .catch(() => undefined)
  await page
    .evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false })))
    .catch(() => undefined)
  await closed
  await page.goto('about:blank').catch(() => undefined)
}

export const test = base.extend<{}, { sessionAPI: APIRequestContext }>({
  sessionAPI: [
    async ({ playwright }, use, workerInfo) => {
      const api = await playwright.request.newContext({ baseURL: workerInfo.project.use.baseURL })
      try {
        await use(api)
      } finally {
        await api.dispose()
      }
    },
    { scope: 'worker' },
  ],
  page: async ({ page, context, sessionAPI }, use) => {
    // Reuse the worker's synthetic login, while retaining a new browser context,
    // page identity and scientific workspace for every test. Relogin after an
    // explicit logout/revocation; production authentication limits stay intact.
    if (!(await sessionAPI.get('/api/v1/auth/me')).ok()) {
      const response = await sessionAPI.post('/api/v1/auth/login', {
        headers: { 'X-SCMM-Client': 'web' },
        data: {
          username: 'browser',
          password: process.env.SCMM_E2E_PASSWORD ?? 'Synthetic browser passphrase',
        },
      })
      expect(response.ok()).toBeTruthy()
    }
    await context.addCookies((await sessionAPI.storageState()).cookies)
    try {
      await use(page)
    } finally {
      await closeDocument(page)
    }
  },
})
