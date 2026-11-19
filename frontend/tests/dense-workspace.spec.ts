import { test, expect, navigate } from './fixtures'
import { importDataset } from './support/project'
test('feature search and default pinned analysis keep the workspace compact', async ({ page }) => {
  await importDataset(page, '紧凑工作区')
  await navigate(page, '/data-editor')
  const names = page.locator('input[aria-label^="特征名称 "]')
  await expect.poll(() => names.count()).toBeLessThanOrEqual(10)
  await expect(names.first()).toBeVisible()
  const groupDraft = page.locator('input[aria-label$=" group"]').first()
  await groupDraft.fill('未应用草稿')
  await page.getByLabel('搜索特征名称', { exact: true }).fill('f0')
  await page.getByRole('button', { name: '查找特征', exact: true }).click()
  await expect(names).toHaveCount(1)
  await expect(groupDraft).toHaveValue('未应用草稿')
  await expect(names.first()).toHaveAttribute('aria-label', '特征名称 f0')
  const matrix = page
    .locator('section.card')
    .filter({ has: page.getByRole('heading', { name: '定量矩阵预览 · 只读' }) })
  await expect(matrix.locator('input')).toHaveCount(0)
  await expect.poll(() => matrix.locator('tbody tr').count()).toBeLessThanOrEqual(10)
  await navigate(page, '/analysis')
  await expect(
    page.getByRole('button', { name: '取消固定参数区', exact: true }).first(),
  ).toHaveAttribute('aria-pressed', 'true')
  await page.setViewportSize({ width: 390, height: 844 })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await navigate(page, '/raw')
  const mass = page.getByLabel('ref_mz', { exact: true })
  await mass.fill('150.123456789')
  await mass.blur()
  await expect(mass).toHaveValue('150.1235')
  await mass.focus()
  await expect(mass).toHaveValue('150.123456789')
})
