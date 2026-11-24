import { finishExport } from './fixtures'
import { navigate, test, expect, type Page, preprocessingStep } from './fixtures'
import { importDataset as importData } from './support/project'

test.use({ actionTimeout: 15000 })

async function noError(page: Page) {
  await expect(page.getByRole('alert')).toHaveCount(0)
}

test('preprocessing preview applies and restores the full origin', async ({ page }) => {
  test.setTimeout(120000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await importData(page, 'Vue 全部分析')
  await navigate(page, '/preprocess')
  await expect(page.getByRole('heading', { name: '预处理' })).toBeVisible()
  await preprocessingStep(page, 'filter').click()
  await expect(page.getByLabel('min_feature_fraction', { exact: true })).toHaveValue('0.2')
  await expect(page.getByRole('heading', { name: '操作前 · 当前数据', exact: true })).toBeVisible()
  await preprocessingStep(page, 'normalize').click()
  await page.getByRole('button', { name: '检查影响', exact: true }).click()
  await expect(page.getByRole('heading', { name: '候选数据（尚未应用）' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '数据规模', exact: true })).toBeVisible()
  await expect(page.getByText('各样本细胞数', { exact: true })).toBeVisible()
  const comparison = page.getByRole('table', { name: '操作前后 QC 对比' })
  await expect(comparison.getByRole('columnheader')).toHaveText([
    '来源文件',
    '指标',
    '统计量',
    '操作前',
    '候选后',
    '变化',
  ])
  await expect
    .poll(() =>
      comparison
        .locator('th')
        .first()
        .evaluate((el) => getComputedStyle(el).textAlign),
    )
    .toBe('center')
  const detected = comparison.locator('tr').filter({ hasText: '检出特征数' }).first()
  await expect(detected.locator('td').nth(3)).toHaveText(/^\d+(\.\d)?$/)
  await page.screenshot({
    path: test.info().outputPath('preprocess-comparison.png'),
    fullPage: true,
  })
  await page.setViewportSize({ width: 390, height: 900 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await noError(page)
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText(
    '预处理已应用，下游分析结果已失效。',
  )
  await page.getByRole('button', { name: '历史与恢复', exact: true }).click()
  await page.getByRole('button', { name: '恢复到预处理起点', exact: true }).click()
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText(
    '已恢复完整预处理起点。',
  )
  expect(errors).toEqual([])
})

test('advanced preprocessing controls stay manual and record applied options', async ({ page }) => {
  await importData(page, '高级预处理')
  await navigate(page, '/preprocess')
  await preprocessingStep(page, 'normalize').click()
  await page.getByText('预处理高级参数', { exact: true }).click()
  await page.getByLabel('归一化总量尺度', { exact: true }).fill('100')
  const pending = page.waitForRequest(
    (r) => r.url().endsWith('/analysis/operation') && !r.postDataJSON().preview,
  )
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  expect((await pending).postDataJSON().options.scale).toBe(100)
  await expect(page.getByRole('button', { name: '应用到当前数据', exact: true })).toBeEnabled()
  const method = page.getByLabel('normalization', { exact: true })
  await expect(method.locator('option')).toHaveCount(4)
  await preprocessingStep(page, 'standardize').click()
  await expect(method.locator('option')).toHaveCount(2)
  await expect(method).toHaveValue('zscore')
  await method.selectOption('minmax')
  const scaled = page.waitForResponse(
    (response) =>
      response.url().endsWith('/analysis/operation') &&
      response.request().postDataJSON()?.options.method === 'minmax',
  )
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  expect((await scaled).ok()).toBe(true)
  await preprocessingStep(page, 'transform').click()
  await expect(method).toHaveCount(0)
  const transformed = page.waitForResponse((response) => {
    if (!response.url().endsWith('/analysis/operation')) return false
    const body = response.request().postDataJSON()
    return body?.preview && body.options.method === 'log'
  })
  await page.getByRole('button', { name: '检查影响', exact: true }).click()
  expect((await transformed).ok()).toBe(true)
  await preprocessingStep(page, 'normalize').click()
  await expect(method).toHaveValue('total')
  await preprocessingStep(page, 'standardize').click()
  await expect(method).toHaveValue('minmax')
  await preprocessingStep(page, 'impute').click()
  await page.getByLabel('imputation', { exact: true }).selectOption('knn')
  await page.getByLabel('插补近邻数', { exact: true }).fill('3')
  await page.getByLabel('插补近邻权重', { exact: true }).selectOption('distance')
  const knn = page.waitForRequest(
    (r) => r.url().endsWith('/analysis/operation') && !r.postDataJSON().preview,
  )
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  expect((await knn).postDataJSON().options).toEqual({
    method: 'knn',
    n_neighbors: 3,
    weights: 'distance',
  })
  await expect(page.getByRole('button', { name: '应用到当前数据', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '历史与恢复', exact: true }).click()
  await expect(page.locator('.history-panel')).toContainText('effective_parameters')
  await noError(page)
})

test('explicit ID subset previews, applies and restores full preprocessing origin', async ({
  page,
}) => {
  await importData(page, '稳定ID子集')
  await navigate(page, '/preprocess')
  await preprocessingStep(page, 'subset').click()
  await page.getByLabel('子集特征ID', { exact: true }).fill('f3,f0')
  await page.getByRole('button', { name: '检查影响', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '候选数据（尚未应用）', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  await expect(page.locator('.project-heading')).toContainText(/64\s+细胞 ×\s+2 特征/)
  await page.getByRole('button', { name: '历史与恢复', exact: true }).click()
  await page.getByRole('button', { name: '恢复到预处理起点', exact: true }).click()
  await expect(page.locator('.project-heading')).toContainText(/64\s+细胞 ×\s+8 特征/)
  await noError(page)
})

test('matrix CSV uses editable sample labels without changing analysis groups', async ({
  page,
}) => {
  await importData(page, '矩阵下载')
  await page.route(
    /\/workspace\/results\/matrix\?source=current$/,
    (route) => route.fulfill({ status: 503, json: { detail: '暂时无法读取矩阵' } }),
    { times: 1 },
  )
  await navigate(page, '/preprocess')
  const panel = page.getByRole('region', { name: '矩阵 CSV 下载' })
  await expect(panel.getByText('未能读取矩阵信息。')).toBeVisible()
  await expect(panel.getByRole('button', { name: '下载预处理矩阵 CSV' })).toBeDisabled()
  await panel.getByRole('button', { name: '重试读取' }).click()
  await expect(panel.getByRole('button', { name: '下载预处理矩阵 CSV' })).toBeEnabled()
  await panel.getByRole('button', { name: '下载预处理矩阵 CSV' }).click()
  const dialog = page.getByRole('dialog', { name: 'CSV 导出', exact: true })
  await dialog.getByText('CSV 标签设置', { exact: true }).click()
  await dialog
    .getByLabel(/^CSV 标签 /)
    .first()
    .fill('CustomLabel')
  await dialog.getByRole('button', { name: '预览 CSV', exact: true }).click()
  await expect(dialog.getByRole('status').filter({ hasText: '当前预览 20 行' })).toBeVisible()
  await dialog.getByLabel('预览范围').selectOption('all')
  await expect(dialog.getByRole('status').filter({ hasText: '全部 64 行' })).toBeVisible()
  await dialog.getByLabel('CSV 行页').fill('4')
  await dialog.getByLabel('CSV 行页').press('Tab')
  await expect(dialog.getByRole('rowheader', { name: '64', exact: true })).toBeVisible()
  const download = await finishExport(page, 'CSV 导出', '下载 CSV')
  expect(download.suggestedFilename()).toBe('preprocessed-matrix.csv')
  const stream = await download.createReadStream()
  const chunks = []
  for await (const chunk of stream!) chunks.push(chunk)
  const csv = Buffer.concat(chunks).toString('utf8')
  expect(csv).toMatch(/^Sample,Label,/)
  expect(csv).toContain('CustomLabel')
})

test('QC distributions, sample correlations and wide CSV preview on desktop', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await importData(page, '质控与宽表浏览')
  await navigate(page, '/preprocess')
  await preprocessingStep(page, 'qc').click()
  const qc = page.locator('.qc-settings')
  await qc.getByRole('button', { name: '生成 QC 图', exact: true }).click()
  await expect(page.locator('.plot-shell .gtitle')).toHaveText(
    'QC distributions by sample or batch',
  )
  await qc.getByLabel('图形', { exact: true }).selectOption('sample_correlation')
  await qc.getByLabel('热图色标', { exact: true }).selectOption('Cividis')
  await qc.getByRole('button', { name: '生成 QC 图', exact: true }).click()
  await expect(page.locator('.plot-shell .gtitle')).toHaveText('Sample correlation heatmap')
  await page.getByRole('button', { name: '作图数据导出', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'CSV 导出', exact: true })
  await dialog.getByRole('button', { name: '预览 CSV', exact: true }).click()
  await dialog.getByLabel('归档中的表').selectOption({ label: 'samples.csv' })
  await expect(dialog.getByRole('columnheader', { name: 'sample_id', exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()

  const headers = ['Sample', 'Label', ...Array.from({ length: 36 }, (_, i) => `feature_${i}`)]
  const body = [
    headers.join(','),
    ...Array.from({ length: 43 }, (_, i) =>
      [
        `cell_${i}`,
        '"Line 1, quoted\r\nLine 2"',
        ...Array.from({ length: 36 }, (_, j) => `${i}.${j}`),
      ].join(','),
    ),
  ].join('\r\n')
  await page.route('**/workspace/results/matrix/download', (route) =>
    route.fulfill({ status: 200, contentType: 'text/csv;charset=utf-8', body }),
  )
  await page.getByRole('button', { name: '下载预处理矩阵 CSV', exact: true }).click()
  await dialog.getByLabel('预览范围').selectOption('all')
  await dialog.getByRole('button', { name: '预览 CSV', exact: true }).click()
  await expect(dialog.getByRole('status').filter({ hasText: '全部 43 行 × 38 列' })).toBeVisible()
  await expect(
    dialog.getByRole('cell', { name: 'Line 1, quoted Line 2', exact: true }).first(),
  ).toBeVisible()
  await dialog.getByLabel('CSV 行页').fill('3')
  await dialog.getByLabel('CSV 行页').press('Tab')
  await dialog.getByRole('button', { name: '下一组列', exact: true }).click()
  await expect(dialog.getByRole('columnheader', { name: 'feature_35', exact: true })).toBeVisible()
  const last = dialog
    .getByRole('row')
    .filter({ has: page.getByRole('rowheader', { name: '43', exact: true }) })
  await expect(last).toContainText('42.35')
  await page.screenshot({ path: test.info().outputPath('csv-all-desktop.png') })
  const downloaded = await finishExport(page, 'CSV 导出', '下载 CSV')
  const stream = await downloaded.createReadStream()
  const chunks = []
  for await (const chunk of stream!) chunks.push(chunk)
  expect(Buffer.concat(chunks).toString('utf8')).toBe(body)
})
