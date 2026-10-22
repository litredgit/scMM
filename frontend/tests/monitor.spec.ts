import { test, expect } from './fixtures'

test('monitor opens without creating a workspace and tracks hidden login pages', async ({
  page,
  context,
}) => {
  test.setTimeout(60000)
  const workspaceRequests: string[] = []
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().endsWith('/api/v1/workspaces'))
      workspaceRequests.push(req.url())
  })
  await page.goto('/admin/monitor')
  await expect(page.getByRole('heading', { name: '管理员监控', exact: true })).toBeVisible()
  await expect(page.getByText('生产环境 · 独立检查', { exact: true })).toBeVisible()

  expect(workspaceRequests).toHaveLength(0)
  const snapshot = () =>
    page.evaluate(async () => await (await fetch('/api/v1/admin/monitor')).json())
  await expect
    .poll(async () => (await snapshot()).update_readiness.monitor_pages)
    .toBeGreaterThan(0)
  const other = await context.browser()!.newContext()
  const login = await other.newPage()
  const openedAt = Date.now() / 1000
  await login.goto(new URL('/projects', page.url()).href)
  await expect(login.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  // Other tests' closed pages can expire during this test. Administration
  // deliberately omits lease IDs; scope to this test's new anonymous page.
  const freshLogin = (p: { route: string; username: string; seen: number }) =>
    p.route === '/login' && p.username === '未登录' && p.seen >= openedAt
  await expect
    .poll(async () =>
      (await snapshot()).pages.some(
        (p: {
          route: string
          username: string
          seen: number
          state: string
          monitor_only: boolean
        }) => freshLogin(p) && p.state === 'connected' && !p.monitor_only,
      ),
    )
    .toBeTruthy()
  await page.bringToFront()
  // Emulate a background document's real visibility event in Chromium.
  await login.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expect
    .poll(async () =>
      (await snapshot()).pages.some(
        (p: { route: string; username: string; seen: number; visibility: string }) =>
          freshLogin(p) && p.visibility === 'hidden',
      ),
    )
    .toBeTruthy()
  await expect.poll(async () => (await snapshot()).update_readiness.state).toBe('blocked')
  await login.goto('about:blank')
  await expect.poll(async () => (await snapshot()).pages.some(freshLogin)).toBeFalsy()
  await other.close()
  for (const width of [1440, 700, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBeTruthy()
    await page.screenshot({ path: `/tmp/scmm-monitor/dashboard-${width}.png`, fullPage: true })
  }
})
