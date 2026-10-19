import { test, expect, type Page } from './fixtures'
async function openAnalysis(page: Page) {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('图例与差异交互回归')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '导入已有结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await page.getByRole('button', { name: '导入结果', exact: true }).click()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
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
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
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
