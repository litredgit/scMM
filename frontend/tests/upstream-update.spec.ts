import { test, expect, navigate, type Page } from './fixtures'
import { importDataset } from './support/project'

async function module(page: Page, id: string, name: string) {
  const select = page.getByRole('combobox', { name: '分析功能', exact: true, includeHidden: true })
  if (await select.isVisible()) await select.selectOption(id)
  else await page.getByRole('button', { name, exact: true }).click()
}

test('target correlations, candidate evidence and manual annotation', async ({ page }) => {
  test.setTimeout(120000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await importDataset(page, '上游增强合成检查')
  await navigate(page, '/analysis')
  await module(page, 'exploration', '相关性与集合')
  const panel = page.getByRole('heading', { name: '相关性与集合比较', exact: true }).locator('..')
  await panel.getByLabel('目标变量', { exact: true }).fill('feature:f0')
  await panel.getByRole('button', { name: '计算并绘图' }).click()
  await expect(panel.locator('.js-plotly-plot')).toBeVisible()
  const download = page.waitForEvent('download')
  await panel.getByRole('button', { name: '下载作图数据' }).click()
  expect((await download).suggestedFilename()).toMatch(/\.zip$/)
  await panel.getByLabel('分析方式').selectOption('set_comparison')
  await panel.getByLabel('参与比较的分组（逗号分隔）').fill('a,b')
  await panel.getByRole('button', { name: '计算并绘图' }).click()
  await expect(panel.locator('.js-plotly-plot')).toBeVisible()
  await navigate(page, '/annotation/evidence')
  const annotations = page.locator('.evidence-input')
  await annotations.getByLabel('注释文件', { exact: true }).setInputFiles({
    name: 'manual.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('feature_id,name\nf0,人工名称\n'),
  })
  await annotations.getByRole('button', { name: '预览匹配' }).click()
  await expect(annotations.getByText('匹配 1 · 歧义 0 · 未匹配 7')).toBeVisible()
  await annotations.getByRole('button', { name: '应用注释', exact: true }).click()
  await annotations.getByRole('button', { name: 'MS/MS 搜索', exact: true }).click()
  const text = 'BEGIN IONS\nTITLE=synthetic\nPEPMASS=150\n100 4\n120 1\nEND IONS\n'
  for (const label of ['实测谱文件', '参考谱库'])
    await annotations
      .getByLabel(label, { exact: true })
      .setInputFiles({ name: 'spectrum.mgf', mimeType: 'text/plain', buffer: Buffer.from(text) })
  await annotations.getByLabel('样本池与适用范围').fill('synthetic pooled sample')
  await annotations.getByLabel('最少匹配碎片').fill('2')
  await annotations.getByRole('button', { name: '搜索候选证据' }).click()
  const records = page.locator('.evidence-records')
  await expect(records.getByLabel('已保存证据记录')).not.toHaveValue('')
  const row = records.locator('.msms-results tbody tr').first()
  await expect(row).toContainText('f0')
  await row.getByRole('button').click()
  await expect(records.locator('.fragment-detail .js-plotly-plot')).toBeVisible()
  await records.getByRole('button', { name: '以此测量峰为关联目标' }).click()
  await records.getByRole('button', { name: '预览关联范围' }).click()
  await expect(records.getByText(/输入版本.+pooled sample/)).toBeVisible()
  await records.getByLabel('证据关联理由').fill('synthetic review')
  await records.getByRole('button', { name: '保存证据关联' }).click()
  await expect(row).toContainText('已关联')
  const downloadEvidence = page.waitForEvent('download')
  await records.getByRole('button', { name: '下载完整证据 JSON' }).click()
  expect((await downloadEvidence).suggestedFilename()).toMatch(/annotation-evidence-.+\.json$/)
  expect(errors).toEqual([])
})

test('reversible cell labels and lasso selection events', async ({ page }) => {
  test.setTimeout(90000)
  await importDataset(page, '可逆筛选合成检查')
  await navigate(page, '/preprocess')
  const panel = page.locator('details.selection-labels')
  await expect(panel).not.toHaveAttribute('open', '')
  await panel.locator('summary').click()
  await panel.getByLabel('保留编号（每行一个）').fill('c0\nc1\nc2')
  await panel.getByRole('button', { name: '保存标签', exact: true }).click()
  await expect(panel.getByText('cell_keep_review · 已启用')).toBeVisible()
  await panel.getByRole('button', { name: '关闭筛选', exact: true }).click()
  await expect(panel.getByText('cell_keep_review · 未启用')).toBeVisible()
  await panel.getByLabel('标签来源').selectOption('lasso')
  await panel.getByLabel('圈选横轴变量').selectOption('feature:f0')
  await panel.getByLabel('圈选纵轴变量').selectOption('feature:f1')
  await panel.getByRole('button', { name: '绘制圈选图' }).click()
  await expect(panel.locator('.js-plotly-plot')).toBeVisible()
  const graph = panel.locator('.js-plotly-plot')
  await graph.scrollIntoViewIfNeeded()
  const point = await graph.evaluate((element) => {
    const g = element as unknown as {
      _fullData: { x: number[]; y: number[] }[]
      _fullLayout: {
        dragmode: string
        xaxis: { _offset: number; l2p: (v: number) => number }
        yaxis: { _offset: number; l2p: (v: number) => number }
      }
    }
    const layout = g._fullLayout
    if (layout.dragmode !== 'lasso') throw new Error('Selection plot must start in lasso mode')
    const box = element.getBoundingClientRect()
    return {
      x: box.left + layout.xaxis._offset + layout.xaxis.l2p(g._fullData[0]!.x[3]!),
      y: box.top + layout.yaxis._offset + layout.yaxis.l2p(g._fullData[0]!.y[3]!),
    }
  })
  await page.mouse.move(point.x - 9, point.y - 9)
  await page.mouse.down()
  await page.mouse.move(point.x + 9, point.y - 9, { steps: 5 })
  await page.mouse.move(point.x + 9, point.y + 9, { steps: 5 })
  await page.mouse.move(point.x - 9, point.y + 9, { steps: 5 })
  await page.mouse.move(point.x - 9, point.y - 9, { steps: 5 })
  await page.mouse.up()
  await expect(panel.getByText(/已选 [1-9]\d* 个细胞/)).toBeVisible()
  const saved = page.waitForRequest(
    (request) => request.url().endsWith('/selection-labels') && request.method() === 'POST',
  )
  await panel.getByRole('button', { name: '保存标签', exact: true }).click()
  expect((await saved).postDataJSON().ids).toContain('c3')
  await expect(panel.getByText('cell_keep_review · 已启用')).toBeVisible()
})
