import { test, expect, navigate, type Page } from './fixtures'

test.use({ viewport: { width: 1920, height: 1080 } })

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
const projectName = () => `AI synthetic project ${test.info().testId.slice(-8)}`
async function create(page: Page) {
  await page
    .getByRole('link', { name: /项目首页/ })
    .first()
    .click()
  await page.getByLabel('项目名称', { exact: true }).fill(projectName())
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await expect(page.getByRole('heading', { name: '添加原始文件', exact: true })).toBeVisible()
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

test('maintenance collects the assistant history save promise', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await configure(page)
  await create(page)
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  const assistant = page.getByRole('complementary', { name: 'AI 分析助手' })
  await assistant.getByRole('button', { name: '当前进行到哪一步了？' }).click()
  await expect(assistant.getByText('synthetic answer completed', { exact: true })).toBeVisible()
  const collected = await page.evaluate(async () => {
    const detail = { promises: [] as Promise<unknown>[] }
    window.dispatchEvent(new CustomEvent('scmm-before-maintenance', { detail }))
    await Promise.all(detail.promises)
    return detail.promises.length
  })
  expect(collected).toBe(1)
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
  await assistant.getByRole('button', { name: '说明与上下文' }).click()
  await assistant.getByText('本轮工作区摘要').click()
  await expect(assistant.locator('.ai-summary')).toContainText('samples')
  await expect(assistant.locator('.ai-summary')).not.toContainText('AI synthetic project')
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
  await expect(page.getByRole('heading', { name: '添加原始文件', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  await assistant.getByLabel('问题', { exact: true }).fill('慢回答')
  await assistant.getByRole('button', { name: '发送', exact: true }).click()
  await expect(assistant.getByText('synthetic answer', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await expect(assistant.getByLabel('当前对话').locator('article')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('guide excerpts and safe streamed Markdown in the desktop conversation', async ({ page }) => {
  const media: string[] = []
  page.on('request', (r) => {
    if (r.url().includes('synthetic.example/illustration.png')) media.push(r.url())
  })
  await configure(page)
  await create(page)
  await navigate(page, '/annotation/evidence')
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  const assistant = page.getByRole('complementary', { name: 'AI 分析助手' })
  const help = assistant.getByRole('button', { name: '说明与上下文' })
  const dialog = assistant.getByRole('log', { name: '当前对话' })
  await expect(help).toHaveAttribute('aria-expanded', 'false')
  await expect(assistant.getByText('当前模型 synthetic-model')).toBeHidden()
  const panelBox = (await assistant.locator('.ai-body').boundingBox())!
  const chatBox = (await dialog.boundingBox())!
  const mainBox = (await page.locator('#main-content').boundingBox())!
  expect(chatBox.height / panelBox.height).toBeGreaterThanOrEqual(0.75)
  expect(mainBox.x + mainBox.width).toBeLessThan(panelBox.x)

  const sent = page.waitForRequest((r) => r.url().endsWith('/ai/chat'))
  await assistant.getByRole('button', { name: '查阅本页使用指南' }).click()
  expect((await sent).postDataJSON().page).toBe('annotation-evidence')
  const reply = dialog.locator('article.assistant')
  await expect(reply.getByRole('heading', { name: '审阅步骤' })).toBeVisible()
  await expect(reply.locator('li strong')).toHaveText('核对匹配')
  await expect(reply.locator('ol')).toHaveAttribute('start', '3')
  await expect(reply.getByRole('table')).toBeVisible()
  await expect(reply.locator('pre code')).toContainText('source_key=mz')
  await expect(reply.locator('blockquote')).toContainText('证据与导入')
  await expect(reply.getByText('<em>原始 HTML 作为文字</em>')).toBeVisible()
  await expect(reply.locator('em, img')).toHaveCount(0)
  await expect(reply.getByRole('link')).toHaveCount(1)
  await expect(reply.getByRole('link', { name: '指南链接' })).toHaveAttribute('target', '_blank')
  await expect(reply.getByRole('link', { name: '指南链接' })).toHaveAttribute(
    'rel',
    'noopener noreferrer',
  )
  expect(media).toEqual([])
  await expect(assistant.getByRole('button', { name: '查阅本页使用指南' })).toHaveCount(0)

  await help.click()
  const sources = assistant.getByRole('region', { name: '本轮查阅的文档' })
  await sources.getByText('《特征注释》· 证据与导入', { exact: true }).click()
  await expect(sources.locator('pre')).toContainText('CSV/TSV')
  await expect(assistant.getByText('聊天已加密保存', { exact: true })).toBeVisible()
  await help.click()
  await page.screenshot({ path: test.info().outputPath('assistant-markdown-desktop.png') })
  await page.reload()
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  await expect(reply.getByRole('table')).toBeVisible()
  await help.click()
  await expect(sources.getByText('《特征注释》· 证据与导入', { exact: true })).toBeVisible()
})

test('long history stays readable while complete turns fit the chat limits', async ({ page }) => {
  const history = Array.from({ length: 12 }, (_, i) => [
    { role: 'user', content: `历史问题 ${i}` + '问'.repeat(500) },
    {
      role: 'assistant',
      content: `历史回答 ${i}\n\n` + '普通历史内容的正文示例。\n\n'.repeat(385),
    },
  ]).flat()
  await page.route('**/api/v1/ai/history?**', async (route) => {
    const response = await route.fetch()
    const saved = await response.json()
    await route.fulfill({
      response,
      json: {
        ...saved,
        messages: [
          ...history,
          { role: 'user', content: '超长回答的问题' },
          { role: 'assistant', content: '长'.repeat(8100) },
          { role: 'user', content: '中止的问题' },
          { role: 'assistant', content: '不完整', note: '已停止' },
        ],
      },
    })
  })
  await configure(page)
  await create(page)
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  const assistant = page.getByRole('complementary', { name: 'AI 分析助手' })
  const dialog = assistant.getByRole('log', { name: '当前对话' })
  const jump = assistant.getByRole('button', { name: '回到最新消息' })
  await expect(dialog.locator('article')).toHaveCount(28)
  await dialog.evaluate((view) => (view.scrollTop = 0))
  await expect(jump).toBeVisible()
  await jump.click()
  await expect(jump).toBeHidden()

  await assistant.getByLabel('问题', { exact: true }).fill('长对话后继续提问')
  const sent = page.waitForRequest((r) => r.url().endsWith('/ai/chat'))
  await assistant.getByRole('button', { name: '发送', exact: true }).click()
  const messages = (await sent).postDataJSON().messages as { role: string; content: string }[]
  expect(messages.length).toBeGreaterThan(1)
  expect(messages.reduce((size, turn) => size + turn.content.length, 0)).toBeLessThanOrEqual(48000)
  expect(messages.at(-1)).toEqual({ role: 'user', content: '长对话后继续提问' })
  expect(
    messages.some((turn) => turn.content === '超长回答的问题' || turn.content === '中止的问题'),
  ).toBe(false)
  expect(messages.every((turn, i) => turn.role === (i % 2 ? 'assistant' : 'user'))).toBe(true)
  await expect(dialog.getByText('synthetic answer', { exact: true })).toBeInViewport()
  await dialog.evaluate((view) => (view.scrollTop = 0))
  await expect(jump).toBeVisible()
  const latest = dialog.getByText('synthetic answer completed', { exact: true })
  await expect(latest).toBeAttached()
  expect(await dialog.evaluate((view) => view.scrollTop)).toBe(0)
  await jump.click()
  await expect(latest).toBeInViewport()
  await expect(dialog.locator('article')).toHaveCount(30)
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
    await panel.getByRole('button', { name: '说明与上下文' }).click()
    await expect(panel.getByText('当前模型 synthetic-model')).toBeVisible()
    const late = page.waitForResponse(
      async (response) =>
        response.url().endsWith('/ai/config') &&
        response.request().method() === 'GET' &&
        !(await response.json()).configured,
    )
    release()
    await (await late).finished()
    await expect(panel.getByText('当前模型 synthetic-model')).toBeVisible()
    await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
    await panel.getByLabel('问题', { exact: true }).fill('配置读取顺序检查')
    await panel.getByRole('button', { name: '发送', exact: true }).click()
    await expect(panel.getByText('synthetic answer completed', { exact: true })).toBeVisible()
  } finally {
    release()
  }
})
