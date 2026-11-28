import {
  test as base,
  expect,
  type Page,
  type APIRequestContext,
  type Locator,
  type Response,
} from '@playwright/test'
export type { Page } from '@playwright/test'
export { expect }

export async function renderAfter(page: Page, response: Response) {
  await response.finished()
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
      }),
  )
}

export function preprocessingStep(page: Page, key: string) {
  const labels: Record<string, string> = {
    remove_outliers: '异常值处理',
    filter: '筛选',
    impute: '零值插补',
    normalize: '归一化',
    standardize: '标准化',
    transform: '数值变换',
    gate: '细胞圈门',
    qc: 'QC 检查',
    subset: '按稳定 ID 取子集',
  }
  return page
    .getByRole('group', { name: '预处理操作', exact: true })
    .getByRole('button', { name: labels[key] ?? key, exact: true })
}

export async function openImageExport(page: Page, button: Locator, format = 'svg') {
  await button.click()
  const dialog = page.getByRole('dialog', { name: '图片导出', exact: true })
  await dialog.getByLabel('图片格式').selectOption(format)
  return dialog
}

export async function finishExport(page: Page, title: string, button: string) {
  const dialog = page.getByRole('dialog', { name: title, exact: true })
  const pending = page.waitForEvent('download')
  await dialog.getByRole('button', { name: button, exact: true }).click()
  const download = await pending
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  return download
}

export async function pinAnalysisParameters(page: Page) {
  const pin = page.getByRole('button', { name: '固定参数区', exact: true }).first()
  const unpin = page.getByRole('button', { name: '取消固定参数区', exact: true }).first()
  await expect(pin.or(unpin)).toBeVisible()
  if (await pin.isVisible()) await pin.click()
}

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
  if (step && path.startsWith('/preprocess')) {
    const button = preprocessingStep(page, step)
    if (await button.count()) await button.click()
  }
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
