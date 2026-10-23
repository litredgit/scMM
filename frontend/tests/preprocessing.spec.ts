import { test, expect, type Page } from './fixtures'
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
  await page.getByRole('link', { name: /预处理/ }).click()
  await expect(page.getByRole('heading', { name: '预处理与 QC' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '操作前 · 当前数据', exact: true })).toBeVisible()
  await page.getByLabel('下一项操作', { exact: true }).selectOption('normalize')
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
  await page.getByRole('link', { name: /预处理/ }).click()
  await page.getByLabel('下一项操作', { exact: true }).selectOption('normalize')
  await page.getByText('预处理高级参数', { exact: true }).click()
  await page.getByLabel('归一化总量尺度', { exact: true }).fill('100')
  const pending = page.waitForRequest(
    (r) => r.url().endsWith('/analysis/operation') && !r.postDataJSON().preview,
  )
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  expect((await pending).postDataJSON().options.scale).toBe(100)
  await expect(page.getByRole('button', { name: '应用到当前数据', exact: true })).toBeEnabled()
  await page.getByLabel('下一项操作', { exact: true }).selectOption('impute')
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
  await page.getByRole('link', { name: /预处理/ }).click()
  await page.getByLabel('下一项操作', { exact: true }).selectOption('subset')
  await page.getByLabel('子集特征ID', { exact: true }).fill('f3,f0')
  await page.getByRole('button', { name: '检查影响', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '候选数据（尚未应用）', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  await expect(page.locator('.page-title').getByText(/64 细胞 × 2 特征/)).toBeVisible()
  await page.getByRole('button', { name: '历史与恢复', exact: true }).click()
  await page.getByRole('button', { name: '恢复到预处理起点', exact: true }).click()
  await expect(page.locator('.page-title').getByText(/64 细胞 × 8 特征/)).toBeVisible()
  await noError(page)
})
