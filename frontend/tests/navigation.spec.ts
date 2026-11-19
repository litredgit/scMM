import { navigate, test, expect } from './fixtures'

test('continuous extraction and statistics steps guard missing quantitative data', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('步骤切换验收')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  const navigation = page.getByRole('navigation', { name: '步骤切换', exact: true })
  await expect(navigation.getByRole('button', { name: /上一步：项目首页/ })).toBeEnabled()
  await navigation.getByRole('button', { name: /下一步：预览/ }).click()
  await expect(page).toHaveURL(/\/raw$/)
  await navigation.getByRole('button', { name: /下一步：提取/ }).click()
  await expect(page).toHaveURL(/\/extraction$/)
  await expect(navigation.getByRole('button', { name: /下一步：预处理/ })).toBeDisabled()
  await expect(navigation.getByText(/请先审核纳入提取结果/)).toBeVisible()
  await navigation.getByRole('button', { name: /上一步：预览/ }).click()
  await navigation.getByRole('button', { name: /上一步：添加原始文件/ }).click()
  await page.getByRole('button', { name: '导入 H5AD 数据', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
  for (const target of ['raw', 'extraction', 'preprocess', 'analysis', 'results']) {
    await navigation.getByRole('button', { name: /下一步：/ }).click()
    await expect(page).toHaveURL(new RegExp(`/${target}$`))
    await expect(page.getByRole('alert')).toHaveCount(0)
  }
  await expect(navigation.getByRole('button', { name: /下一步：/ })).toHaveCount(0)
  for (const target of ['analysis', 'preprocess', 'extraction', 'raw', 'samples', 'projects']) {
    await navigation.getByRole('button', { name: /上一步：/ }).click()
    await expect(page).toHaveURL(new RegExp(`/${target}$`))
  }
  await expect(navigation).toHaveCount(0)
  expect(errors).toEqual([])
})

test('three independent modules expose their own inputs and remain usable on narrow screens', async ({
  page,
}) => {
  await page.goto('/')
  const directory = page.locator('.module-catalog')
  await expect(directory).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('module-directory-desktop.png') })
  const modules = page.getByRole('navigation', { name: '工作流程', exact: true })
  for (const [name, path] of [
    ['细胞提取', '/cell-extraction'],
    ['特征注释', '/annotation'],
    ['统计分析', '/statistics'],
  ]) {
    await navigate(page, path!)
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect(page.getByRole('heading', { name: name!, exact: true })).toBeVisible()
    await expect(page.getByRole('region', { name: '板块数据导入与导出' })).toContainText(
      '创建或打开项目',
    )
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(modules.getByRole('button', { name: /细胞提取/ })).toBeVisible()
  await expect(modules.getByRole('button', { name: /特征注释/ })).toBeVisible()
  await expect(modules.getByRole('button', { name: /统计分析/ })).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
  ).toBeTruthy()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  for (const width of [1024, 760, 390]) {
    await page.setViewportSize({ width, height: 844 })
    await expect(directory).toHaveCount(0)
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
      .toBe(true)
  }
  await page.screenshot({ path: test.info().outputPath('module-directory-mobile.png') })
})

test('statistics imports an external sample matrix directly and exports a portable package', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('独立统计入口')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await navigate(page, '/statistics')
  const exchange = page.getByRole('region', { name: '板块数据导入与导出' })
  await exchange.getByRole('button', { name: '导入外部数据' }).click()
  await exchange.getByLabel('板块导入格式').selectOption('matrix_csv')
  await exchange.getByLabel('观测单位').selectOption('sample')
  await exchange.getByLabel('板块数据文件').setInputFiles({
    name: 'samples.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'Sample,Class,150.0,151.003355\ns1,A,10,2\ns2,A,12,3\ns3,B,25,5\ns4,B,28,6\n',
    ),
  })
  await exchange.getByRole('button', { name: '检查并导入本板块' }).click()
  await expect(exchange).toContainText('4 个样本')
  await expect(exchange).toContainText('2 个特征')
  const download = page.waitForEvent('download')
  await exchange.getByRole('button', { name: '导出本板块数据' }).click()
  expect((await download).suggestedFilename()).toMatch(/scmm-exchange\.zip$/)
  await navigate(page, '/preprocess?step=normalize')
  await expect(page.getByLabel('下一项操作', { exact: true })).toHaveValue('normalize')
  await navigate(page, '/preprocess?step=filter')
  await expect(page.getByLabel('下一项操作', { exact: true })).toHaveValue('filter')
  await expect(page.getByRole('heading', { name: '预处理', exact: true })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('feature-only annotation import cannot enable quantitative statistics', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('独立特征输入')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await navigate(page, '/annotation')
  const exchange = page.getByRole('region', { name: '板块数据导入与导出' })
  await exchange.getByRole('button', { name: '导入外部数据' }).click()
  await exchange.getByLabel('板块导入格式').selectOption('feature_csv')
  await exchange.getByLabel('板块数据文件').setInputFiles({
    name: 'features.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('feature_id,mz\nf1,150\nf2,151.003355\n'),
  })
  await exchange.getByRole('button', { name: '检查并导入本板块' }).click()
  await expect(exchange).toContainText('独立特征表可用于注释')
  await navigate(page, '/statistics')
  await expect(
    page.locator('.state-note').filter({ hasText: /统计分析需要定量矩阵。请在上方/ }),
  ).toBeVisible()
  await expect(page.getByRole('button').filter({ hasText: '数据检查' })).toBeDisabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('mass spectrum controls preserve source values while changing display and viewport', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('统一谱图工具')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.getByRole('link', { name: /预览/ }).click()
  await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
  await page.getByRole('button', { name: '单扫描', exact: true }).click()
  await page.getByRole('button', { name: '更新图形', exact: true }).click()
  const plot = page.locator('.mass-spectrum-shell')
  const graph = plot.locator('.js-plotly-plot')
  await expect(graph).toBeVisible()
  const source = await graph.evaluate((el) =>
    JSON.stringify(
      (el as HTMLElement & { layout: { meta: { export_tables: unknown } } }).layout.meta
        .export_tables,
    ),
  )
  await plot.getByLabel('谱图强度显示').selectOption({ label: '相对丰度（基峰 100%）' })
  await expect
    .poll(() =>
      graph.evaluate((el) =>
        Math.max(...(el as HTMLElement & { data: { y: number[] }[] }).data[0]!.y),
      ),
    )
    .toBe(100)
  expect(
    await graph.evaluate((el) =>
      JSON.stringify(
        (el as HTMLElement & { layout: { meta: { export_tables: unknown } } }).layout.meta
          .export_tables,
      ),
    ),
  ).toBe(source)
  await plot
    .locator('summary')
    .filter({ hasText: /^峰标签$/ })
    .click()
  await expect
    .poll(() =>
      graph.evaluate((el) =>
        (
          el as HTMLElement & { layout: { annotations: { text: string }[] } }
        ).layout.annotations.some((item) => item.text === '150.0000'),
      ),
    )
    .toBe(true)
  const before = await graph.evaluate(
    (el) => (el as HTMLElement & { layout: { yaxis: { range: number[] } } }).layout.yaxis.range[1],
  )
  await plot.getByRole('button', { name: '纵轴放大', exact: true }).click()
  await expect
    .poll(() =>
      graph.evaluate(
        (el) =>
          (el as HTMLElement & { layout: { yaxis: { range: number[] } } }).layout.yaxis.range[1],
      ),
    )
    .toBeLessThan(before!)
  await plot.getByRole('button', { name: '恢复全谱', exact: true }).click()
  await expect
    .poll(() =>
      graph.evaluate(
        (el) =>
          (el as HTMLElement & { layout: { xaxis: { autorange: boolean } } }).layout.xaxis
            .autorange,
      ),
    )
    .toBe(true)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('each workflow page restores its own scroll and first visits start at top', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('逐页滚动')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('link', { name: /预览/ }).click()
  await expect(page.getByRole('heading', { name: '预览', exact: true })).toBeVisible()
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            window.scrollTo(0, 400)
            resolve()
          }),
        ),
      ),
  )
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(100)
  const rawPosition = await page.evaluate(() => scrollY)
  // DOM clicks avoid Playwright first scrolling the sidebar link into view.
  await page.getByRole('link', { name: /提取/ }).evaluate((el: HTMLAnchorElement) => el.click())
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0)
  await page.getByRole('link', { name: /预览/ }).evaluate((el: HTMLAnchorElement) => el.click())
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(rawPosition)
})

test('project drafts survive workspace refresh and saving does not apply them', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('草稿状态')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByLabel('项目备注', { exact: true }).fill('尚未应用的说明')
  await expect(page.locator('.draft-state')).toContainText('项目信息')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByLabel('项目备注', { exact: true })).toHaveValue('尚未应用的说明')
  await expect(page.locator('.draft-state')).toContainText('项目信息')
  await expect(page.locator('.save-state')).toHaveText('已保存')
  await page.getByRole('button', { name: '应用项目信息', exact: true }).click()
  await expect(page.locator('.save-state')).toHaveText('已应用未保存')
  await expect(page.locator('.draft-state')).toHaveCount(0)
})
