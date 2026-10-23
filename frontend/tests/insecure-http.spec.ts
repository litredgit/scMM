import { test, expect } from '@playwright/test'

// A non-loopback HTTP origin exercises the browser's actual insecure-context behavior.
test.use({
  launchOptions: {
    ...(process.env.SCMM_CHROMIUM ? { executablePath: process.env.SCMM_CHROMIUM } : {}),
    // The synthetic origin must bypass inherited host proxy settings as well.
    env: {
      ...process.env,
      HTTP_PROXY: '',
      HTTPS_PROXY: '',
      ALL_PROXY: '',
      http_proxy: '',
      https_proxy: '',
      all_proxy: '',
    },
    args: ['--no-proxy-server', '--host-resolver-rules=MAP scmm.test 127.0.0.1'],
  },
})

test('internal HTTP loads login and monitoring with document registration', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  const registration = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/presence/register') &&
      response.request().method() === 'POST',
  )
  await page.goto(`http://scmm.test:${process.env.SCMM_E2E_PORT ?? '5117'}/admin/monitor`)
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.isSecureContext)).toBe(false)
  expect((await registration).status()).toBe(200)
  await page.getByLabel('账号', { exact: true }).fill('browser')
  await page
    .getByLabel('密码', { exact: true })
    .fill(process.env.SCMM_E2E_PASSWORD ?? 'Synthetic browser passphrase')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '管理员监控', exact: true })).toBeVisible()
  await expect
    .poll(async () =>
      page.evaluate(async () => {
        const response = await fetch('/api/v1/admin/monitor')
        return response.ok && (await response.json()).update_readiness.monitor_pages
      }),
    )
    .toBeGreaterThan(0)
  expect(errors).toEqual([])
  await page.goto('about:blank')
})
