import { test, expect, type Page } from './fixtures'

async function configure(page: Page, navigate = true) {
  if (navigate) await page.goto('/account')
  const form = page.getByRole('form', { name: '个人 AI API 配置' })
  await form.getByLabel('Base URL').fill('https://synthetic.example/v1')
  await form.getByLabel('Model', { exact: true }).fill('synthetic-model')
  await form.getByLabel('API Key').fill('synthetic-secret-browser')
  await form.getByRole('button', { name: '保存 API 配置' }).click()
  await expect(form.getByText('个人 API 配置已保存。')).toBeVisible()
  await expect(form.getByLabel('API Key')).toHaveValue('')
  return form
}
const projectName = () => `AI synthetic project ${test.info().repeatEachIndex}`
async function create(page: Page) {
  await page
    .getByRole('link', { name: /项目首页/ })
    .first()
    .click()
  await page.getByLabel('项目名称', { exact: true }).fill(projectName())
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
}

test('personal API configuration, test, persistence and delete', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  const form = await configure(page)
  await form.getByRole('button', { name: '测试连接' }).click()
  await expect(form.getByText(/连接测试通过/)).toBeVisible()
  await page.reload()
  await expect(form.getByText('API Key：已配置，可替换或删除')).toBeVisible()
  await expect(form.getByLabel('API Key')).toHaveValue('')
  await expect(form.getByLabel('Model', { exact: true })).toHaveValue('synthetic-model')
  const storage = await page.evaluate(() =>
    JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
  )
  expect(storage).not.toContain('synthetic-secret-browser')
  await form.getByRole('button', { name: '删除 API 配置' }).click()
  await expect(form.getByText('API Key：未配置')).toBeVisible()
  expect(errors).toEqual([])
})

test('stream, context, cross-page retention, stop, clear, refresh and project switch', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await configure(page)
  await create(page)
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  const assistant = page.getByRole('complementary', { name: 'AI 分析助手' })
  await assistant.getByRole('button', { name: '当前进行到哪一步了？' }).click()
  await expect(assistant.getByText('synthetic answer completed', { exact: true })).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('assistant-desktop.png') })
  await assistant.getByText('本次发送的上下文').click()
  await expect(assistant.locator('pre')).toContainText('samples')
  await expect(assistant.locator('pre')).not.toContainText('AI synthetic project')
  await page.getByRole('link', { name: /参数参考/ }).click()
  await expect(assistant.getByText('synthetic answer completed', { exact: true })).toBeVisible()
  await assistant.getByLabel('问题', { exact: true }).fill('慢回答')
  await assistant.getByRole('button', { name: '发送', exact: true }).click()
  await expect(assistant.getByText('synthetic answer', { exact: true })).toBeVisible()
  await assistant.getByRole('button', { name: '停止生成' }).click()
  await expect(assistant.getByText('已停止生成；已接收部分仅供参考。')).toBeVisible()
  await assistant.getByRole('button', { name: '清空对话' }).click()
  await expect(assistant.getByLabel('当前对话').locator('article')).toHaveCount(0)
  await expect(assistant.locator('details')).toHaveCount(0)
  await assistant.getByRole('button', { name: '下一步建议做什么？' }).click()
  await expect(assistant.getByText('synthetic answer completed', { exact: true })).toBeVisible()
  await expect(assistant.getByText('聊天已加密保存', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  await expect(assistant.getByLabel('当前对话').locator('article')).toHaveCount(2)
  await assistant.getByRole('button', { name: '收起 AI 助手', exact: true }).click()
  await page
    .getByRole('link', { name: /项目首页/ })
    .first()
    .click()
  await page
    .getByRole('row')
    .filter({ hasText: projectName() })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  await assistant.getByLabel('问题', { exact: true }).fill('慢回答')
  await assistant.getByRole('button', { name: '发送', exact: true }).click()
  await expect(assistant.getByText('synthetic answer', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await expect(assistant.getByLabel('当前对话').locator('article')).toHaveCount(0)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: test.info().outputPath('assistant-390.png') })
  expect(errors).toEqual([])
})

test('logout cancels pending answer and clears conversation', async ({ page }) => {
  await configure(page)
  await page
    .getByRole('link', { name: /项目首页/ })
    .first()
    .click()
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  const assistant = page.getByRole('complementary', { name: 'AI 分析助手' })
  await assistant.getByLabel('问题', { exact: true }).fill('慢回答')
  await assistant.getByRole('button', { name: '发送', exact: true }).click()
  await expect(assistant.getByText('synthetic answer', { exact: true })).toBeVisible()
  await page.locator('.account-menu > summary').click()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(assistant).toHaveCount(0)
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
})

test('slow initial configuration cannot overwrite editable credentials', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/ai/config', async (route) => {
    if (route.request().method() === 'GET') await gate
    await route.continue()
  })
  try {
    await page.goto('/account')
    const form = page.getByRole('form', { name: '个人 AI API 配置' })
    await expect(form.getByLabel('Base URL')).toBeDisabled()
    await expect(form.getByLabel('Model', { exact: true })).toBeDisabled()
    await expect(form.getByLabel('API Key')).toBeDisabled()
    release()
    await form.getByLabel('Base URL').fill('https://synthetic.example/v1')
    await form.getByLabel('Model', { exact: true }).fill('synthetic-model')
    const syntheticKey = 'synthetic-secret-browser'
    await form.getByLabel('API Key').fill(syntheticKey)
    const saved = page.waitForRequest((r) => r.url().endsWith('/ai/config') && r.method() === 'PUT')
    await form.getByRole('button', { name: '保存 API 配置' }).click()
    expect((await saved).postDataJSON()).toEqual({
      base_url: 'https://synthetic.example/v1',
      model: 'synthetic-model',
      api_key: syntheticKey,
    })
    await expect(form.getByText('个人 API 配置已保存。')).toBeVisible()
  } finally {
    release()
  }
})

test('slow history restore protects the question draft until recovery completes', async ({
  page,
}) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/ai/history?**', async (route) => {
    if (route.request().method() === 'GET') await gate
    await route.continue()
  })
  try {
    await configure(page)
    await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
    await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
    const panel = page.getByRole('complementary', { name: 'AI 分析助手' })
    await expect(panel.getByLabel('问题', { exact: true })).toBeDisabled()
    await expect(
      panel.getByRole('button', { name: '当前进行到哪一步了？', exact: true }),
    ).toBeDisabled()
    release()
    await panel.getByLabel('问题', { exact: true }).fill('恢复后保留的问题')
    const sent = page.waitForRequest((r) => r.url().endsWith('/ai/chat'))
    await panel.getByRole('button', { name: '发送', exact: true }).click()
    expect((await sent).postDataJSON().messages.at(-1).content).toBe('恢复后保留的问题')
    await expect(panel.getByText('synthetic answer completed', { exact: true })).toBeVisible()
  } finally {
    release()
  }
})

test('late initial assistant configuration cannot undo a newly saved configuration', async ({
  page,
}) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let held = false
  await page.route('**/api/v1/ai/config', async (route) => {
    if (!held && route.request().method() === 'GET') {
      held = true
      await gate
      await route.fulfill({ json: { available: true, configured: false, model: '', base_url: '' } })
    } else await route.continue()
  })
  try {
    await page.goto('/')
    await page.getByRole('link', { name: '账号与管理', exact: true }).click()
    await configure(page, false)
    // The saved configuration has triggered a newer assistant read.
    await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
    const panel = page.getByRole('complementary', { name: 'AI 分析助手' })
    await expect(panel.getByText('只读解释与建议 · 当前模型：synthetic-model')).toBeVisible()
    const late = page.waitForResponse(
      async (response) =>
        response.url().endsWith('/ai/config') &&
        response.request().method() === 'GET' &&
        !(await response.json()).configured,
    )
    release()
    await (await late).finished()
    await expect(panel.getByText('只读解释与建议 · 当前模型：synthetic-model')).toBeVisible()
    await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
    await panel.getByLabel('问题', { exact: true }).fill('配置读取顺序检查')
    await panel.getByRole('button', { name: '发送', exact: true }).click()
    await expect(panel.getByText('synthetic answer completed', { exact: true })).toBeVisible()
  } finally {
    release()
  }
})
