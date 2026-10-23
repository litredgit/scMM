import { test as base, expect, type Page, type APIRequestContext } from '@playwright/test'
export type { Page } from '@playwright/test'
export { expect }

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
