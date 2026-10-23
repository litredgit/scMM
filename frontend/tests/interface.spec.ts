import { test, expect, type Page } from './fixtures'
async function openAnalysis(page: Page) {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('图例与差异交互回归')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^(?:▤ )?analysis[.]h5ad\s/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await page.getByRole('button', { name: '固定参数区', exact: true }).first().click()
}
test('legend reorder persists, selection is manual and six steps fit narrow screens', async ({
  page,
}) => {
  test.setTimeout(90000)
  await openAnalysis(page)
  await page.getByRole('button', { name: '运行降维', exact: true }).click()
  const plot = page
    .locator('.plot-shell')
    .filter({ has: page.getByLabel('图文件名：X_pca', { exact: true }) })
  await expect(plot.locator('.legendtext')).toHaveText(['a', 'b'])
  const colors = await plot
    .locator('.js-plotly-plot')
    .evaluate((el) =>
      (el as HTMLElement & { data: { name: string; marker?: { color?: unknown } }[] }).data.map(
        (t) => [t.name, t.marker?.color],
      ),
    )
  await plot.locator('.legend-order > summary').click()
  await plot.getByRole('button', { name: '下移图例 a', exact: true }).click()
  await expect(plot.locator('.legendtext')).toHaveText(['b', 'a'])
  expect(
    await plot
      .locator('.js-plotly-plot')
      .evaluate((el) =>
        (el as HTMLElement & { data: { name: string; marker?: { color?: unknown } }[] }).data.map(
          (t) => [t.name, t.marker?.color],
        ),
      ),
  ).toEqual(colors)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '图例与差异交互回归' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await page.getByRole('button', { name: '更新嵌入图', exact: true }).click()
  await expect(plot.locator('.legendtext')).toHaveText(['b', 'a'])
  await plot.locator('.legend-order > summary').click()
  await plot.getByRole('button', { name: '恢复图例默认顺序', exact: true }).click()
  await expect(plot.locator('.legendtext')).toHaveText(['a', 'b'])
  await page.getByRole('button', { name: '差异与 Marker', exact: true }).click()
  await expect(page.getByRole('heading', { name: '各组差异 Marker', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '计算两组差异并绘制火山图', exact: true }).click()
  let plots = 0
  page.on('request', (r) => {
    if (r.url().endsWith('/analysis/plot') && r.postDataJSON().kind === 'violin') plots++
  })
  await page.getByRole('checkbox', { name: '选择小提琴特征 f0', exact: true }).check()
  await page.getByRole('checkbox', { name: '选择小提琴特征 f1', exact: true }).check()
  await page.getByRole('button', { name: '上移特征 f1', exact: true }).click()
  await page.getByLabel('小提琴搜索特征', { exact: true }).fill('f7')
  await expect(page.getByRole('checkbox', { name: '选择小提琴特征 f7', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '移除特征 f0', exact: true })).toBeVisible()
  expect(plots).toBe(0)
  const drawn = page.waitForRequest(
    (r) => r.url().endsWith('/analysis/plot') && r.postDataJSON().kind === 'violin',
  )
  await page.getByRole('button', { name: '绘制小提琴图', exact: true }).click()
  expect((await drawn).postDataJSON().options.features).toEqual(['f1', 'f0'])
  await expect(
    page.getByText('选择或显示设置已变更，点击“绘制小提琴图”更新。', { exact: true }),
  ).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('difference-desktop.png'), fullPage: true })
  for (const width of [700, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
    await page.screenshot({
      path: test.info().outputPath(`difference-${width}.png`),
      fullPage: true,
    })
    for (const route of [
      '/samples',
      '/raw',
      '/extraction',
      '/preprocess',
      '/analysis',
      '/results',
    ]) {
      await page.locator(`.sidebar nav a[href='${route}']`).click()
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true)
    }
    await page.screenshot({
      path: test.info().outputPath(`six-steps-${width}.png`),
      fullPage: true,
    })
  }
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('parameter scope, unapplied drafts and saved project state stay distinct', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('参数范围状态检查')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  const reference = page.getByLabel('ref_mz', { exact: true })
  await expect(reference).not.toHaveValue('')
  const original = await reference.inputValue()
  await reference.fill('150')
  await expect(page.getByLabel('参数生效状态')).toContainText('与所选范围的生效配置不同')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state')).toHaveText('已保存')
  await expect(page.getByLabel('参数生效状态')).toContainText('表单与当前样本正式提取参数不同')
  await page.getByLabel('参数应用范围').selectOption('sample')
  const applySample = page.waitForRequest(
    (r) => r.url().endsWith('/parameters') && r.method() === 'PUT',
  )
  await page.getByRole('button', { name: '应用参数', exact: true }).click()
  expect((await applySample).postDataJSON().sample_id).toBeTruthy()
  await expect(page.getByLabel('参数生效状态')).toContainText('与所选范围的生效配置一致')
  await expect(page.getByLabel('参数生效状态')).toContainText('当前样本使用样本例外')
  await reference.fill('151')
  await page.getByLabel('参数应用范围').selectOption('project')
  const applyProject = page.waitForRequest(
    (r) => r.url().endsWith('/parameters') && r.method() === 'PUT',
  )
  await page.getByRole('button', { name: '应用参数', exact: true }).click()
  expect((await applyProject).postDataJSON().sample_id).toBeNull()
  await expect(page.getByLabel('参数生效状态')).toContainText('与所选范围的生效配置一致')
  await expect(page.getByLabel('参数生效状态')).toContainText('表单与当前样本正式提取参数不同')
  await page.getByLabel('参数应用范围').selectOption('sample')
  await expect(page.getByLabel('参数生效状态')).toContainText('与所选范围的生效配置不同')
  await page.route('**/workspace/parameters', async (route) => {
    if (route.request().method() !== 'PUT') return route.continue()
    await route.fulfill({
      status: 422,
      json: { error: { code: 'synthetic', message: '合成参数应用失败' } },
    })
  })
  await page.getByRole('button', { name: '应用参数', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('合成参数应用失败')
  await expect(page.getByLabel('参数生效状态')).toContainText('与所选范围的生效配置不同')
  await page.unroute('**/workspace/parameters')
  await page.getByRole('button', { name: '清除样本例外', exact: true }).click()
  await expect(reference).toHaveValue('151')
  await expect(page.getByLabel('参数生效状态')).toContainText('与所选范围的生效配置一致')
  expect(original).not.toBe('151')
})

test('desktop figures, direct exports, assistant space and compact mobile navigation', async ({
  page,
}) => {
  test.setTimeout(60000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.setViewportSize({ width: 1920, height: 1080 })
  await openAnalysis(page)
  await page.getByRole('button', { name: '运行降维', exact: true }).click()
  await expect(page.locator('.analysis-visualization .js-plotly-plot')).toBeVisible()
  const inputBox = await page.locator('.analysis-calculation').first().boundingBox()
  const figureBox = await page.locator('.analysis-visualization').first().boundingBox()
  expect(figureBox!.x).toBeGreaterThan(inputBox!.x + inputBox!.width)
  expect(figureBox!.width).toBeGreaterThan(inputBox!.width)
  await page.screenshot({
    path: test.info().outputPath('layout-analysis-1920.png'),
    fullPage: true,
  })
  await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
  const assistant = await page.locator('.ai-assistant').boundingBox()
  const content = await page.locator('.analysis-content').boundingBox()
  expect(content!.x + content!.width).toBeLessThanOrEqual(assistant!.x)
  await page.getByRole('button', { name: '收起 AI 助手', exact: true }).click()
  await page.getByRole('link', { name: /结果与保存/ }).click()
  const download = await page
    .getByRole('button', { name: '下载完整结果', exact: true })
    .boundingBox()
  expect(download!.y).toBeLessThan(1080)
  await page.screenshot({ path: test.info().outputPath('layout-results-1920.png'), fullPage: true })
  for (const width of [2560, 1440, 700, 390]) {
    await page.setViewportSize({ width, height: 1080 })
    for (const route of [
      '/samples',
      '/raw',
      '/extraction',
      '/preprocess',
      '/analysis',
      '/results',
    ]) {
      await page.locator(`.sidebar nav a[href='${route}']`).click()
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true)
      if (width === 390) {
        await page.evaluate(() => window.scrollTo(0, 0))
        const title = await page.getByRole('heading', { level: 1 }).boundingBox()
        expect(title!.y).toBeLessThan(350)
      }
    }
  }
  await page.screenshot({ path: test.info().outputPath('layout-mobile-390.png'), fullPage: true })
  await page.getByRole('button', { name: '流程与账号', exact: true }).click()
  await expect(page.getByRole('link', { name: '账号与管理', exact: true })).toBeVisible()
  expect(errors).toEqual([])
})

test('a delayed batch summary cannot label the next project as awaiting review', async ({
  page,
}) => {
  let release: () => void = () => {}
  let captured: () => void = () => {}
  const received = new Promise<void>((resolve) => {
    captured = resolve
  })
  const waiting = new Promise<void>((resolve) => {
    release = resolve
  })
  let first = true
  await page.route('**/workspace/extraction/batches', async (route) => {
    if (!first) return route.continue()
    first = false
    const response = await route.fetch()
    captured()
    await waiting
    await route.fulfill({
      response,
      json: [
        { path: 'old-batch', status: 'completed', samples: [{ id: 'old', status: 'succeeded' }] },
      ],
    })
  })
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('迟到批次来源项目')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await received
  try {
    await page.getByRole('button', { name: '关闭项目', exact: true }).click()
    await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
    await page.getByLabel('项目名称', { exact: true }).fill('迟到批次目标项目')
    await page.getByRole('button', { name: '创建并添加样本' }).click()
    const status = page.locator('.sidebar a[href="/extraction"] .nav-step-state')
    await expect(status).toHaveText('未开始')
    const lateResponse = page.waitForResponse(
      async (response) =>
        response.url().endsWith('/extraction/batches') &&
        (await response.json())[0]?.path === 'old-batch',
    )
    release()
    await lateResponse
    await expect(status).toHaveText('未开始')
    await expect(page.locator('.project-heading')).toContainText('迟到批次目标项目')
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally {
    release()
  }
})

for (const [width, height] of [
  [1366, 768],
  [1440, 900],
  [1920, 1080],
  [390, 844],
]) {
  test(`result-first layout preserves plot width and main view at ${width}x${height}`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height })
    await openAnalysis(page)
    // This helper pins controls for the pre-existing parameter editing regressions.
    await page.getByRole('button', { name: '取消固定参数区', exact: true }).first().click()
    await page.getByRole('button', { name: '运行降维', exact: true }).click()
    const plot = page.locator('.analysis-visualization .js-plotly-plot').first()
    await expect(plot).toBeVisible()
    await expect(
      page.getByRole('button', { name: '展开计算参数', exact: true }).first(),
    ).toBeVisible()
    await expect(page.getByLabel('store_key', { exact: true })).not.toBeVisible()
    await page.screenshot({ path: test.info().outputPath(`result-first-viewport-${width}.png`) })
    if (width >= 1000) {
      await expect
        .poll(async () => {
          const box = await plot.boundingBox()
          return (
            !!box && Math.min(height, box.y + box.height) - Math.max(80, box.y) >= box.height * 0.6
          )
        })
        .toBe(true)
      const before = (await plot.boundingBox())!.width
      await page.getByRole('button', { name: 'AI 分析助手', exact: true }).click()
      await expect
        .poll(async () => (await plot.boundingBox())!.width)
        .toBeGreaterThan(width < 1800 ? before - 2 : 600)
      await page.getByRole('button', { name: '收起 AI 助手', exact: true }).click()
    }
    await page.getByRole('button', { name: '固定参数区', exact: true }).first().click()
    await expect(page.getByLabel('store_key', { exact: true })).toBeVisible()
    await page.getByLabel('store_key', { exact: true }).fill('X_tuning_draft')
    await page.getByRole('button', { name: '取消固定参数区', exact: true }).first().click()
    await page.getByRole('button', { name: '展开计算参数', exact: true }).first().click()
    await expect(page.getByLabel('store_key', { exact: true })).toHaveValue('X_tuning_draft')
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
    await page.screenshot({
      path: test.info().outputPath(`result-first-${width}.png`),
      fullPage: true,
    })
  })
}

test('raw m/z bounds stay paired beside the spectrum at laptop widths', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('原始参数笔记本布局')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await expect(page.getByLabel('mz_min', { exact: true })).toBeVisible()
  for (const width of [1366, 1440, 1920, 390]) {
    await page.setViewportSize({ width, height: 900 })
    const min = (await page.getByLabel('mz_min', { exact: true }).boundingBox())!
    const max = (await page.getByLabel('mz_max', { exact: true }).boundingBox())!
    expect(Math.abs(min.y - max.y)).toBeLessThan(2)
    expect(max.x).toBeGreaterThan(min.x)
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
    await page.screenshot({
      path: test.info().outputPath(`raw-paired-${width}.png`),
      fullPage: true,
    })
  }
})
