import { test, expect, type Page } from '@playwright/test'

async function create(page: Page, name: string) {
  await page.goto('/')
  await expect(page.getByRole('row').filter({ hasText: '已有项目' })).toBeVisible()
  await page.getByLabel('项目名称', { exact: true }).fill(name)
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
}

test('project, samples, metadata, save and reopen with no browser errors', async ({
  page,
  context,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await create(page, '浏览器全流程')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /alpha.mzML/ }).click()
  await page.getByRole('button', { name: /beta.mzXML/ }).click()
  await page.getByRole('button', { name: '添加 2 个文件', exact: true }).click()
  await expect(page.getByLabel('alpha group', { exact: true })).toBeVisible()
  await page.getByLabel('alpha group', { exact: true }).fill('对照')
  await page.getByLabel('alpha group', { exact: true }).press('Tab')
  await expect(page.getByRole('status')).toHaveText('样本信息已更新。')
  await page.getByLabel('alpha subject', { exact: true }).fill('animal-1')
  await page.getByLabel('alpha subject', { exact: true }).press('Tab')
  await expect(page.getByRole('status')).toHaveText('样本信息已更新。')
  await expect(page.getByText('有未保存修改', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()

  // A second tab starts with an independent workspace, even in the same context.
  const other = await context.newPage()
  await other.goto('/samples')
  await expect(other.getByRole('heading', { name: '先选择一个项目' })).toBeVisible()
  await other.close()

  await page.reload()
  await expect(page.getByRole('heading', { name: '先选择一个项目' })).toBeVisible()
  await page.getByRole('link', { name: '前往项目首页 →' }).click()
  const row = page.getByRole('row').filter({ hasText: '浏览器全流程' })
  await row.getByRole('button', { name: '打开项目 →' }).click()
  await expect(page.getByLabel('alpha group', { exact: true })).toHaveValue('对照')
  await expect(page.getByLabel('alpha subject', { exact: true })).toHaveValue('animal-1')
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()

  await page.screenshot({ path: test.info().outputPath('samples-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 700, height: 1050 })
  await expect(page.getByRole('button', { name: '保存项目', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  )
  await page.screenshot({ path: test.info().outputPath('samples-700.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('dataset import, mapping, CSV and snapshot reload', async ({ page }) => {
  await create(page, '导入与保存')
  await page.getByRole('button', { name: '导入已有结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /example.h5ad/ }).click()
  await page.getByRole('button', { name: '导入结果', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
  await expect(page.getByLabel('映射 alpha')).not.toHaveValue('')
  await page.getByLabel('导入样本信息 CSV').setInputFiles({
    name: 'metadata.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('name,subject,batch\nalpha,animal-1,批次A\nbeta,animal-2,批次A'),
  })
  await expect(page.getByLabel('alpha subject', { exact: true })).toHaveValue('animal-1')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: /结果与保存/ }).click()
  await expect(page.getByText('6 细胞 × 4 特征', { exact: true })).toBeVisible()
  await expect(page.getByText(/baseline.h5ad/)).toBeVisible()
  await page.getByRole('link', { name: /参数参考/ }).click()
  await expect(page.getByRole('cell', { name: 'snr_v1', exact: true })).toHaveCount(2)
  await page.reload()
  await page
    .getByRole('link', { name: /项目首页/, exact: false })
    .first()
    .click()
  await page
    .getByRole('row')
    .filter({ hasText: '导入与保存' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByLabel('alpha batch', { exact: true })).toHaveValue('批次A')
})

test('invalid sample edit leaves saved data unchanged and allows retry', async ({ page }) => {
  await create(page, '错误恢复')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /alpha.mzML/ }).click()
  await page.getByRole('button', { name: /beta.mzXML/ }).click()
  await page.getByRole('button', { name: '添加 2 个文件', exact: true }).click()
  await page.getByLabel('beta name', { exact: true }).fill('alpha')
  await page.getByLabel('alpha name', { exact: true }).last().press('Tab')
  await expect(page.getByRole('alert')).toBeVisible()
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect(page.getByLabel('beta name', { exact: true })).toHaveValue('beta')
  await page.getByLabel('beta name', { exact: true }).fill('beta-renamed')
  await page.getByLabel('beta-renamed name', { exact: true }).press('Tab')
  await expect(page.getByRole('status')).toHaveText('样本信息已更新。')
})
