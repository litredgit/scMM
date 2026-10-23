import { test, expect, type Page } from './fixtures'
import { importDataset as importData } from './support/project'

test.use({ actionTimeout: 15000 })

async function noError(page: Page) {
  await expect(page.getByRole('alert')).toHaveCount(0)
}

async function analysisModule(page: Page, id: string, label: string) {
  const select = page.getByRole('combobox', { name: '分析功能', exact: true, includeHidden: true })
  await expect(select).toBeAttached()
  if (await select.isVisible()) await select.selectOption(id)
  else await page.getByRole('button', { name: label, exact: true }).click()
}

test('analysis panels, precision export and snapshot restore', async ({ page }) => {
  test.setTimeout(120000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await importData(page, '独立分析与重载')
  // This journey owns its preprocessing origin and retained input layer.
  await page.getByRole('link', { name: /预处理/ }).click()
  await page.getByRole('button', { name: '检查影响', exact: true }).click()
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('预处理已应用，下游分析结果已失效。')
  await page.getByRole('button', { name: '历史与恢复', exact: true }).click()
  await page.getByRole('button', { name: '恢复到预处理起点', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('已恢复完整预处理起点。')
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await page.getByRole('button', { name: '运行降维', exact: true }).click()
  await expect(page.getByLabel('查看嵌入', { exact: true })).toHaveValue('X_pca')
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible()
  await page.getByLabel('store_key', { exact: true }).fill('X_pca_compare')
  await page.getByRole('button', { name: '运行降维', exact: true }).click()
  await expect(page.getByLabel('查看嵌入', { exact: true })).toHaveValue('X_pca_compare')
  await expect(page.getByRole('button', { name: '更新嵌入图', exact: true })).toBeEnabled()
  const switchedEmbedding = page.waitForResponse(
    (response) =>
      response.url().endsWith('/analysis/plot') &&
      response.request().postDataJSON().options.key === 'X_pca',
  )
  await page.getByLabel('查看嵌入', { exact: true }).selectOption('X_pca')
  expect((await switchedEmbedding).ok()).toBe(true)
  await page.getByRole('button', { name: '聚类', exact: true }).click()
  await page.getByRole('button', { name: '运行聚类', exact: true }).click()
  await expect(page.getByLabel('Color', { exact: true })).toHaveValue('obs:clusters')
  await page.getByLabel('Color source', { exact: true }).selectOption('feature')
  const autoPlot = page.waitForResponse(async (response) => {
    if (!response.url().endsWith('/analysis/plot')) return false
    const body = response.request().postDataJSON()
    return body.kind === 'embedding' && body.options.color === 'feature:f0'
  })
  await page.getByLabel('Color', { exact: true }).selectOption('feature:f0')
  expect((await autoPlot).ok()).toBe(true)
  await expect(page.getByRole('button', { name: '更新嵌入图', exact: true })).toBeEnabled()
  const uncolored = page.waitForResponse(
    (response) =>
      response.url().endsWith('/analysis/plot') &&
      response.request().postDataJSON().options.color === null,
  )
  await page.getByLabel('Color source', { exact: true }).selectOption('none')
  expect((await uncolored).ok()).toBe(true)
  await noError(page)
  await analysisModule(page, 'differential', '差异与 Marker')
  await page.getByRole('button', { name: '计算两组差异并绘制火山图', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'differential', exact: true })).toBeVisible()
  await page.getByRole('checkbox', { name: '选择小提琴特征 f0', exact: true }).check()
  await page.getByRole('button', { name: '绘制小提琴图', exact: true }).click()
  await page.getByRole('button', { name: '计算全部簇 Marker', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'markers', exact: true })).toBeVisible()
  await analysisModule(page, 'network', '相关网络')
  await page.getByRole('button', { name: '计算相关网络', exact: true }).click()
  await expect(page.locator('.js-plotly-plot').last()).toBeVisible()
  await noError(page)
  await analysisModule(page, 'supervised', '监督与 SHAP')
  await page.getByRole('combobox', { name: 'model', exact: true }).selectOption('lda')
  await page.getByLabel('cv', { exact: true }).fill('2')
  await page.getByLabel('test_size', { exact: true }).fill('0.5')
  await page.getByRole('button', { name: '训练并验证', exact: true }).click()
  const validationNotes = page.getByRole('complementary', { name: '监督验证解释', exact: true })
  await expect(validationNotes).toContainText('细胞数不等于生物重复')
  await expect(validationNotes).toContainText('不再是独立测试')
  await expect(
    page.getByRole('button', { name: '保存潜变量和 train/test 标识', exact: true }),
  ).toBeEnabled()
  await noError(page)
  await page.getByRole('button', { name: '保存潜变量和 train/test 标识', exact: true }).click()
  await page.getByLabel('shap_background', { exact: true }).fill('4')
  await page.getByLabel('shap_samples', { exact: true }).fill('2')
  await page.getByRole('button', { name: '解释当前模型（SHAP）', exact: true }).click()
  await expect(page.getByRole('button', { name: '读取 SHAP', exact: true })).toBeVisible({
    timeout: 30000,
  })
  await noError(page)
  await page.getByRole('combobox', { name: '图例', exact: true }).selectOption('hidden')
  await page.getByRole('button', { name: '应用视图设置', exact: true }).click()
  await page.setViewportSize({ width: 700, height: 1000 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true)
  await page.screenshot({ path: test.info().outputPath('analysis-700.png'), fullPage: true })
  await page.getByRole('link', { name: /结果与保存/ }).click()
  await page.getByLabel('H5AD 文件名', { exact: true }).fill('vue-export.h5ad')
  await page.getByRole('combobox', { name: '保存存储', exact: true }).selectOption('Results')
  await page.getByRole('button', { name: '导出当前 H5AD（不覆盖）', exact: true }).click()
  await expect(page.getByText(/已导出：.*vue-export.h5ad/)).toBeVisible()
  await page.getByRole('combobox', { name: '下载内容', exact: true }).selectOption('differential')
  const downloaded = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载完整结果', exact: true }).click()
  expect((await downloaded).suggestedFilename()).toBe('differential.csv')
  await page.getByRole('button', { name: '保存项目', exact: true }).last().click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.reload()
  await page.getByRole('link', { name: 'scMM 项目首页' }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '独立分析与重载' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await analysisModule(page, 'supervised', '监督与 SHAP')
  await expect(
    page.getByRole('button', { name: '解释当前模型（SHAP）', exact: true }),
  ).toBeDisabled()
  await expect(page.getByRole('combobox', { name: '图例', exact: true })).toHaveValue('hidden')
  await page.getByRole('button', { name: '读取监督诊断', exact: true }).click()
  await expect(validationNotes).toContainText('细胞数不等于生物重复')
  await noError(page)
  await analysisModule(page, 'differential', '差异与 Marker')
  const invalidated = page.waitForResponse((response) =>
    response.url().endsWith('/analysis/invalidate'),
  )
  await page.getByRole('combobox', { name: 'layer', exact: true }).selectOption('scmm_input_0')
  const invalidation = await invalidated
  expect(invalidation.status()).toBe(200)
  expect(invalidation.request().postDataJSON().names.sort()).toEqual(['differential', 'markers'])
  await analysisModule(page, 'network', '相关网络')
  await expect(page.getByRole('combobox', { name: 'layer', exact: true })).toHaveValue('当前矩阵')
  await expect(page.getByRole('button', { name: '读取相关网络', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /结果与保存/ }).click()
  await expect(
    page
      .getByRole('combobox', { name: '下载内容', exact: true })
      .locator('option[value="differential"]'),
  ).toHaveCount(0)
  expect(errors).toEqual([])
})
