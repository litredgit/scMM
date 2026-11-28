import { finishExport } from './fixtures'
import { test, expect, navigate } from './fixtures'
import { createProject, importDataset } from './support/project'

test('desktop analysis keeps core methods visible and follows server plugin selection', async ({
  page,
}) => {
  test.setTimeout(60_000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await importDataset(page, '方法协议桌面验证')
  const config = await page.request.get('/api/v1/configuration')
  expect(config.ok()).toBeTruthy()
  const { enabled_plugins: enabled, methods } = await config.json()
  await navigate(page, '/analysis')
  const nav = page.getByRole('navigation', { name: '分析功能' })
  await expect(nav.getByRole('button', { name: '降维', exact: true })).toBeInViewport()
  await expect(nav.getByRole('button', { name: '聚类', exact: true })).toBeInViewport()
  for (const [id, title] of Object.entries({
    network: '相关网络',
    supervised: '监督与 SHAP',
    time: '伪时间与轨迹',
  })) {
    await expect(nav.getByRole('button', { name: title, exact: true })).toHaveCount(
      enabled.includes(id) ? 1 : 0,
    )
  }
  await expect(
    page.getByLabel('reduction', { exact: true }).locator('option[value="umap"]'),
  ).toHaveCount(1)
  const installed = methods.some((method: { id: string }) => method.id === 'fixture-methods:report')
  const extension = page
    .locator('details')
    .filter({ has: page.getByText('插件方法', { exact: true }) })
  await expect(extension).toHaveCount(installed ? 1 : 0)
  if (installed) {
    await expect(extension).toHaveAttribute('data-scmm-draft-owner', 'analysis/method/reduction')
    await nav.getByRole('button', { name: '差异与 Marker' }).click()
    await expect(extension).toHaveAttribute('data-scmm-draft-owner', 'analysis/method/statistics')
    await extension.locator('summary').click()
    await extension.getByLabel('选择插件方法').selectOption('fixture-methods:report')
    await extension.getByLabel('分组列', { exact: true }).selectOption('group')
    await expect(extension.getByRole('button', { name: '运行插件方法' })).toBeInViewport()
    await extension.getByRole('button', { name: '运行插件方法' }).click()
    await expect(extension.getByRole('button', { name: '下载完整 CSV' })).toBeVisible()
    await extension.getByRole('button', { name: '下载完整 CSV' }).click()
    const download = finishExport(page, 'CSV 导出', '下载 CSV')
    expect((await download).suggestedFilename()).toBe('fixture-methods-report.csv')
    await navigate(page, '/results')
    await page.locator('summary').filter({ hasText: '插件方法报告' }).click()
    await expect(page.getByRole('button', { name: '下载完整 CSV' })).toBeVisible()

    await createProject(page, '方法协议提取预览')
    await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
    await page.getByRole('button', { name: /extract.mzML/ }).click()
    await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
    await navigate(page, '/raw')
    await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
    const raw = page.locator('.raw-parameter-panel')
    await raw.locator('summary').filter({ hasText: '提取方法（项目级）' }).click()
    await raw.getByLabel('细胞识别方法', { exact: true }).selectOption('fixture-methods:detect')
    await raw.getByLabel('特征定量方法', { exact: true }).selectOption('fixture-methods:quantify')
    for (const [field, value] of Object.entries({ ref_mz: '150', mz_min: '140', mz_max: '160' })) {
      await raw.getByLabel(field, { exact: true }).fill(value)
    }
    await raw.getByRole('button', { name: '应用参数', exact: true }).click()
    await raw.getByRole('button', { name: '预览细胞窗口', exact: true }).click()
    await expect(page.getByText(/检出 1 个细胞/)).toBeVisible({ timeout: 20000 })
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  expect(overflow).toBe(false)
  expect(errors).toEqual([])
})
