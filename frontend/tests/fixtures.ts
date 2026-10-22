import { test as base, expect, type Page } from '@playwright/test'
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

export const test = base.extend({
  page: async ({ page, context }, use) => {
    const response = await context.request.post('/api/v1/auth/login', {
      headers: { 'X-SCMM-Client': 'web' },
      data: {
        username: 'browser',
        password: process.env.SCMM_E2E_PASSWORD ?? 'Synthetic browser passphrase',
      },
    })
    expect(response.ok()).toBeTruthy()
    try {
      await use(page)
    } finally {
      // Playwright context destruction does not reliably dispatch a real
      // document pagehide. Navigate first so each test closes its own lease.
      await closeDocument(page)
    }
  },
})
