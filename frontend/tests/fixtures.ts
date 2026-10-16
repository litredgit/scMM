import { test as base, expect } from '@playwright/test'
export type { Page } from '@playwright/test'
export { expect }

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
    await use(page)
  },
})
