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

test('closing during a delayed registration sends a terminal proof before the response', async ({
  page,
}) => {
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const registering = new Promise<void>((resolve) => {
    entered = resolve
  })
  let first = true
  await page.route('**/presence/register', async (route) => {
    if (first && !route.request().postDataJSON().closed) {
      first = false
      entered()
      await held
    }
    await route.continue().catch(() => {})
  })
  try {
    await page.goto('/projects')
    await registering
    const terminal = page.waitForResponse(
      (r) => r.url().endsWith('/presence/register') && r.request().postDataJSON().closed,
    )
    await page.evaluate(() =>
      window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: false })),
    )
    const response = await terminal
    expect(response.ok()).toBe(true)
    const proof = response.request().postDataJSON()
    expect(proof.registration_secret.length).toBeGreaterThanOrEqual(32)
    await page.goto('about:blank')
    release()
    const late = await page.request.post('/api/v1/presence/register', {
      headers: { 'X-SCMM-Client': 'web' },
      data: { ...proof, closed: false },
    })
    expect(late.status()).toBe(409)
  } finally {
    release()
  }
})

test('a cached document confirmed closed acquires a new lease on resume', async ({ page }) => {
  const first = page.waitForResponse((r) => r.url().endsWith('/presence/register') && r.ok())
  await page.goto('/projects')
  const original = (await first).request().postDataJSON()
  await expect(page.getByRole('heading', { name: '创建项目', exact: true })).toBeVisible()
  const close = await page.request.post('/api/v1/presence/register', {
    headers: { 'X-SCMM-Client': 'web' },
    data: { ...original, closed: true },
  })
  expect(close.ok()).toBe(true)
  const renewed = page.waitForResponse(
    (r) =>
      r.url().endsWith('/presence/register') &&
      r.ok() &&
      r.request().postDataJSON().id !== original.id,
  )
  await page.evaluate(() =>
    window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })),
  )
  const fresh = await renewed
  expect(fresh.request().postDataJSON().registration_secret).not.toBe(original.registration_secret)
  const stale = await page.request.post('/api/v1/presence/register', {
    headers: { 'X-SCMM-Client': 'web' },
    data: original,
  })
  expect(stale.status()).toBe(409)
})

test('administrator closure review clears an orphan without replacing workspace checkpoint', async ({
  page,
}) => {
  await page.goto('/account')
  await expect(page.getByRole('heading', { name: '服务器资源与更新', exact: true })).toBeVisible()
  const orphan = await page.request.post('/api/v1/presence/register', {
    headers: { 'X-SCMM-Client': 'web' },
    data: { id: crypto.randomUUID().replaceAll('-', ''), route: '/login', visibility: 'suspended' },
  })
  expect(orphan.ok()).toBe(true)
  await page.getByRole('button', { name: '收集全部会话', exact: true }).click()
  try {
    await page.getByRole('button', { name: '读取失联页面范围', exact: true }).click()
    await expect(page.getByText(/本轮失联 1 页/)).toBeVisible()
    await page.getByLabel('页面关闭依据', { exact: true }).fill('已核实本轮孤立测试页面关闭')
    await page.getByRole('button', { name: '记录关闭确认并保留工作区', exact: true }).click()
    await expect(
      page.getByText('关闭依据已记录；工作区仍保留，请继续验证并暂存会话。', { exact: true }),
    ).toBeVisible()
    await expect
      .poll(async () => {
        const r = await page.request.get('/api/v1/admin/maintenance/status')
        return (await r.json()).acknowledged.length
      })
      .toBeGreaterThan(0)
    const checkpoint = page.waitForResponse((r) =>
      r.url().endsWith('/admin/maintenance/checkpoint'),
    )
    await page.getByRole('button', { name: '验证并暂存会话', exact: true }).click()
    const checked = await checkpoint
    expect(checked.ok(), await checked.text()).toBe(true)
    await expect
      .poll(async () => {
        const r = await page.request.get('/api/v1/admin/maintenance/status')
        return Boolean((await r.json()).completed?.verified)
      })
      .toBe(true)
  } finally {
    await page.getByRole('button', { name: '取消维护', exact: true }).click()
  }
})
