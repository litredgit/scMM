import { test, expect, type Page } from './fixtures'

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
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText('样本信息已更新。')
  await page.getByLabel('alpha subject', { exact: true }).fill('animal-1')
  await page.getByLabel('alpha subject', { exact: true }).press('Tab')
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText('样本信息已更新。')
  await expect(page.getByText('已应用未保存', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()

  // A second tab starts with an independent workspace, even in the same context.
  const other = await context.newPage()
  await other.goto('/samples')
  await expect(other.getByRole('heading', { name: '先选择一个项目' })).toBeVisible()
  await other.goto('about:blank')
  await other.close()

  await page.reload()
  await expect(page.getByLabel('alpha group', { exact: true })).toHaveValue('对照')
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: '前往项目首页 →' }).click()
  const row = page.getByRole('row').filter({ hasText: '浏览器全流程' })
  await row.getByRole('button', { name: '打开项目 →' }).click()
  await expect(page.getByLabel('alpha group', { exact: true })).toHaveValue('对照')
  await expect(page.getByLabel('alpha subject', { exact: true })).toHaveValue('animal-1')
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()

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
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ example.h5ad/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
  await expect(page.getByLabel('映射 alpha', { exact: true })).not.toHaveValue('')
  await page.getByLabel('导入样本信息 CSV', { exact: true }).setInputFiles({
    name: 'metadata.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('name,subject,batch\nalpha,animal-1,批次A\nbeta,animal-2,批次A'),
  })
  await expect(page.getByLabel('alpha subject', { exact: true })).toHaveValue('animal-1')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('link', { name: /结果与保存/ }).click()
  await page.getByText('项目快照详情', { exact: true }).click()
  await expect(
    page.locator('#main-content').getByText('6 细胞 × 4 特征', { exact: true }),
  ).toBeVisible()
  await expect(page.locator('dd').filter({ hasText: 'baseline.h5ad' })).toBeVisible()
  await page.getByRole('link', { name: /参数参考/ }).click()
  await expect(page.getByRole('cell', { name: 'snr', exact: true })).toHaveCount(2)
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
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.locator('a[href="/samples"]').first().click()
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
  await expect(page.getByLabel('alpha name', { exact: true }).last()).toHaveValue('alpha')
  await expect(page.locator('.draft-state')).toContainText('样本信息')
  const workspace = await page.evaluate(() => sessionStorage.getItem('scmm-workspace')!)
  const response = await page.request.get('/api/v1/workspace', {
    headers: { 'X-SCMM-Workspace': workspace },
  })
  expect(
    (await response.json()).project.manifest.samples.map((sample: { name: string }) => sample.name),
  ).toEqual(['alpha', 'beta'])
  await page.getByLabel('alpha name', { exact: true }).last().fill('beta-renamed')
  await page.getByLabel('beta-renamed name', { exact: true }).press('Tab')
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText('样本信息已更新。')
})

test('processed merge explicitly maps sources, previews ref and restores the full union baseline', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await create(page, '独立矩阵合并')
  const panel = page
    .locator('details')
    .filter({ has: page.locator('summary').filter({ hasText: '合并已处理矩阵' }) })
  await panel.locator('summary').click()
  for (const [i, file, name] of [
    [1, 'merge-left.h5ad', 'merged-left'],
    [2, 'merge-right.h5ad', 'merged-right'],
  ] as const) {
    await panel.getByRole('button', { name: '选择合并结果文件', exact: true }).click()
    await panel.getByLabel('合并来源存储', { exact: true }).selectOption('Results')
    await panel.getByLabel('合并来源路径', { exact: true }).fill(file)
    await panel.getByRole('button', { name: '添加所选合并文件', exact: true }).click()
    await panel.getByLabel(`合并输入 ${i} 的 m/z 来源`, { exact: true }).selectOption('mz')
    await panel.getByLabel(`合并输入 ${i} 的样本来源`, { exact: true }).selectOption('sample')
    await panel.getByLabel(`合并输入 ${i} 样本 1 目标名`, { exact: true }).fill(name)
  }
  await expect(
    panel.getByRole('button', { name: '预览已处理矩阵合并', exact: true }),
  ).toBeDisabled()
  await panel.getByLabel('合并参考集', { exact: true }).selectOption('0')
  await panel.getByLabel('合并特征范围', { exact: true }).selectOption('ref')
  await panel.getByLabel('合并共同观察字段', { exact: true }).fill('time')
  const reviewing = page.waitForResponse((r) => r.url().endsWith('/dataset/merge/preview'))
  await panel.getByRole('button', { name: '预览已处理矩阵合并', exact: true }).click()
  const review = await (await reviewing).json()
  expect(review.workspace.project.dataset).toBeNull()
  expect(review.value.summaries.data.features).toBe(2)
  expect(review.value.summaries.baseline.features).toBe(3)
  const previewDownload = page.waitForEvent('download')
  await panel.getByRole('button', { name: '下载完整合并预览', exact: true }).click()
  expect((await previewDownload).suggestedFilename()).toBe('scmm-merge-preview.zip')
  const applying = page.waitForResponse((r) => r.url().endsWith('/dataset/merge/apply'))
  await panel.getByRole('button', { name: '合并并替换当前数据和起点', exact: true }).click()
  const applied = await (await applying).json()
  expect(applied.project.dataset.cells).toBe(3)
  expect(applied.project.dataset.features).toBe(2)
  await expect(panel.getByRole('heading', { name: '历史合并溯源', exact: true })).toBeVisible()
  const auditDownload = page.waitForEvent('download')
  await panel.getByRole('button', { name: '下载历史合并溯源', exact: true }).click()
  expect((await auditDownload).suggestedFilename()).toBe('scmm-merge-audit.zip')
  for (const width of [700, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
  }
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.reload()
  const restored = page
    .locator('details')
    .filter({ has: page.locator('summary').filter({ hasText: '合并已处理矩阵' }) })
  if (!(await restored.getByRole('heading', { name: '历史合并溯源', exact: true }).isVisible()))
    await restored.locator('summary').click()
  await expect(restored.getByRole('heading', { name: '历史合并溯源', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /预处理/ }).click()
  await page.getByRole('button', { name: '历史与恢复', exact: true }).click()
  const resetting = page.waitForResponse(
    (r) =>
      r.url().endsWith('/analysis/operation') && r.request().postDataJSON()?.operation === 'reset',
  )
  await page.getByRole('button', { name: '恢复到预处理起点', exact: true }).click()
  const reset = await (await resetting).json()
  expect(reset.project.dataset.features).toBe(3)
  expect(reset.project.dataset.cells).toBe(3)
  expect(errors).toEqual([])
})
