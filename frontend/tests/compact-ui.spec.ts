import { test, expect, navigate } from './fixtures'
import { createProject } from './support/project'
test('compact sidebar exposes three modules and restores active workflow', async ({ page }) => {
  await createProject(page, '紧凑导航验证')
  const nav = page.getByRole('navigation', { name: '工作流程', exact: true })
  for (const name of ['细胞提取', '特征注释', '统计分析'])
    await expect(nav.getByRole('button', { name, exact: true })).toBeVisible()
  await navigate(page, '/annotation')
  await expect(page.getByRole('region', { name: '本页概况' })).toBeVisible()
  await navigate(page, '/statistics')
  await navigate(page, '/preprocess?step=filter')
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
    .toBe(true)
  await expect(page.locator('.module-tabs')).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('compact-desktop.png') })
})
