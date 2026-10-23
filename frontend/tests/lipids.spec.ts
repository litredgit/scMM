import { test, expect } from './fixtures'
import { readFile } from 'node:fs/promises'

test('lipid rules, isotope review, filtered adduct CSV and saved versions', async ({ page }) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  async function selectFeature(id: string) {
    const query = page.waitForResponse(
      (response) =>
        response.url().endsWith('/lipids/query') &&
        response.request().postDataJSON().feature_id === id,
    )
    await page.getByLabel('脂质逐特征核对', { exact: true }).selectOption(id)
    const response = await query
    expect(response.ok()).toBe(true)
    await response.finished()
    await expect(page.getByRole('button', { name: '保存人工指定', exact: true })).toBeEnabled()
    for (const details of await page.locator('.lipid-panel tbody details').all()) {
      if ((await details.getAttribute('open')) === null)
        await details.locator(':scope > summary').click()
    }
  }
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('脂质标记验收')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ lipids.h5ad/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await page.getByRole('button', { name: '注释与同位素', exact: true }).click()
  const panel = page.locator('.lipid-panel')
  await expect(panel.getByRole('heading', { name: '注释与同位素', exact: true })).toBeVisible()
  await expect(panel.getByRole('button', { name: '检查本地数据库' })).toBeVisible()
  await expect(page.getByLabel('脂质规则预设').locator('option')).toHaveCount(6)
  await page
    .getByLabel('脂质规则预设')
    .selectOption({ label: '大肠杆菌｜PE/PG/CL 优先｜审阅草案 v1' })
  await expect(panel.locator('summary').filter({ hasText: '查看规则' })).toContainText('78 项')
  await expect(panel.locator('summary').filter({ hasText: '查看规则' })).toContainText('尚未应用')
  const rulePreview = panel.locator('.lipid-rule-preview')
  await rulePreview.locator('summary').click()
  await expect(rulePreview.getByRole('row')).toHaveCount(51)
  await rulePreview.getByRole('button', { name: '规则下一页', exact: true }).click()
  await expect(rulePreview.getByRole('row')).toHaveCount(29)
  await expect(rulePreview.getByRole('button', { name: '规则下一页', exact: true })).toBeDisabled()
  await page.getByLabel('脂质 polarity', { exact: true }).selectOption('neg')
  await expect(panel.getByLabel('[M-H]-', { exact: true })).toBeChecked()
  await page.getByLabel('脂质 polarity', { exact: true }).selectOption('pos')
  const content = JSON.stringify({
    schema_version: 1,
    name: 'browser custom',
    rules: [
      { kind: 'class', level: 'CATEGORY', value: 'GP', score: 7 },
      { kind: 'adduct', polarity: 'pos', adduct: '[M+H]+', score: 3 },
    ],
  })
  await page.getByLabel('导入脂质规则').setInputFiles({
    name: 'rules.json',
    mimeType: 'application/json',
    buffer: Buffer.from(content),
  })
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText(
    '规则已校验，可保存预设或应用排序。',
  )
  await expect(rulePreview.getByRole('row')).toHaveCount(3)
  await page.getByLabel('脂质预设名称', { exact: true }).fill('浏览器规则')
  await page.getByRole('button', { name: '保存为规则预设', exact: true }).click()
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText('规则已保存为预设。')
  await page.getByLabel('脂质规则预设', { exact: true }).selectOption('浏览器规则')
  await expect(page.getByLabel('脂质规则预设', { exact: true }).locator('option')).toHaveCount(7)
  await panel.getByText('相关性辅助注释与网络 · 高级参数', { exact: true }).click()
  await panel.getByLabel('min_joint_cells', { exact: true }).fill('10')
  await page.getByLabel('脂质版本名称').fill('第一次标记')
  await page.getByRole('button', { name: '运行注释与同位素标记', exact: true }).dblclick()
  await expect(panel.getByText('4 / 4 特征 · 4 条候选 · 4 条关系证据')).toBeVisible()
  await expect(page.getByLabel('脂质查看版本').locator('option')).toHaveCount(2)
  await expect(page.getByLabel('annotation_ppm', { exact: true })).not.toBeVisible()
  await expect(
    panel.getByRole('row').filter({ hasText: 'Synthetic lipid A' }).first(),
  ).toBeVisible()
  await expect(
    panel.getByRole('row').filter({ hasText: 'Synthetic lipid B' }).first(),
  ).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  const network = panel.locator('.lipid-network-panel')
  await expect(network.getByRole('img', { name: '注释分类饼图' })).toBeVisible()
  await expect(network.getByRole('button', { name: '网络节点 f_h', exact: true })).toBeVisible()
  await network.getByRole('button', { name: '网络节点 f_h', exact: true }).click()
  await expect(page.getByLabel('脂质逐特征核对', { exact: true })).toHaveValue('f_h')
  await network.getByRole('button', { name: '展开邻居', exact: true }).click()
  await expect(network.getByRole('button', { name: '网络节点 f_h', exact: true })).toBeVisible()
  await network.getByRole('button', { name: '应用图表显示', exact: true }).click()
  let graphDownload = page.waitForEvent('download')
  await network.getByRole('button', { name: '下载网络 SVG', exact: true }).click()
  const svgDownload = await graphDownload
  const svg = await readFile((await svgDownload.path())!, 'utf8')
  expect(svg).toContain('layer=scmm_input_0')
  expect(svg).toContain('annotation_version=')
  expect(svg).toContain('isotopes=all')
  expect(svg).toContain('candidates=all')
  graphDownload = page.waitForEvent('download')
  await network.getByRole('button', { name: '下载饼图 PNG', exact: true }).click()
  expect((await graphDownload).suggestedFilename()).toMatch(/\.png$/)
  await network.getByText('注释图论文导出设置', { exact: true }).click()
  const widthBefore = await network.getByLabel('导出宽度（毫米）', { exact: true }).inputValue()
  const dpiBefore = await network.getByLabel('导出分辨率（DPI）', { exact: true }).inputValue()
  await network.getByLabel('导出宽度（毫米）', { exact: true }).fill('600')
  await network.getByLabel('导出分辨率（DPI）', { exact: true }).fill('2400')
  await network.getByRole('button', { name: '下载饼图 PNG', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('请减小成图尺寸或 DPI。')
  await network.getByLabel('导出宽度（毫米）', { exact: true }).fill(widthBefore)
  await network.getByLabel('导出分辨率（DPI）', { exact: true }).fill(dpiBefore)
  await page.getByRole('button', { name: '清除错误', exact: true }).click()
  await network.getByText('图表高级显示参数', { exact: true }).click()
  await network.getByLabel('node_limit', { exact: true }).fill('1')
  await network.getByRole('button', { name: '应用图表显示', exact: true }).click()
  await expect(
    network.getByText('节点上限只限制显示；搜索或展开邻居可查看其他节点。'),
  ).toBeVisible()
  graphDownload = page.waitForEvent('download')
  await network.getByRole('button', { name: '导出网络节点 CSV', exact: true }).click()
  const nodeDownload = await graphDownload
  const nodeCsv = await readFile((await nodeDownload.path())!, 'utf8')
  expect(nodeCsv.trim().split('\n')).toHaveLength(5)
  await network.getByLabel('node_limit', { exact: true }).fill('100')
  await network.getByRole('button', { name: '应用图表显示', exact: true }).click()
  for (const width of [1440, 700, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true)
    await panel.screenshot({ path: test.info().outputPath(`lipids-${width}.png`) })
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByLabel('同位素状态', { exact: true }).selectOption('hide')
  await page.getByLabel('加合物保留方式', { exact: true }).selectOption('strongest')
  await page.getByRole('button', { name: '应用显示筛选', exact: true }).click()
  await expect(panel.getByText('2 / 4 特征 · 2 条候选 · 4 条关系证据')).toBeVisible()
  let downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出筛选矩阵 CSV', exact: true }).click()
  let download = await downloadPromise
  let csv = await readFile((await download.path())!, 'utf8')
  expect(csv.split('\n')[0]).toBe('Sample,Label,f_h,f_unknown')
  expect(csv.trim().split('\n')).toHaveLength(41)
  await page.getByLabel('加合物保留方式', { exact: true }).selectOption('specified')
  await panel.getByLabel('[M+Na]+', { exact: true }).last().check()
  await page.getByRole('button', { name: '应用显示筛选', exact: true }).click()
  downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出筛选矩阵 CSV', exact: true }).click()
  download = await downloadPromise
  csv = await readFile((await download.path())!, 'utf8')
  expect(csv.split('\n')[0]).toBe('Sample,Label,f_na,f_unknown')

  await page.getByLabel('加合物保留方式', { exact: true }).selectOption('all')
  await page.getByLabel('同位素状态', { exact: true }).selectOption('all')
  await page.getByRole('button', { name: '应用显示筛选', exact: true }).click()
  await selectFeature('f_h')
  await panel.getByLabel('指定 LMGP01010002 [M+H]+', { exact: true }).uncheck()
  await expect(panel.getByLabel('指定 LMGP01010002 [M+H]+', { exact: true })).not.toBeChecked()
  await page.getByRole('button', { name: '保存人工指定', exact: true }).click()
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText('人工指定已保存。')
  await expect(panel.getByLabel('指定 LMGP01010002 [M+H]+', { exact: true })).not.toBeChecked()
  await panel.getByRole('button', { name: '接受', exact: true }).first().click()
  await expect(panel.getByRole('cell', { name: '接受', exact: true }).first()).toBeVisible()
  await network.getByLabel('网络 graph', { exact: true }).selectOption('molecule')
  await network.getByRole('button', { name: '应用图表显示', exact: true }).click()
  await expect(network.getByRole('heading', { name: /分子相关网络/ })).toBeVisible()
  const moleculeNode = network.locator('svg [role="button"]').first()
  await moleculeNode.click()
  await expect(network.getByLabel('representative_feature', { exact: true })).toBeVisible()
  await network.getByRole('button', { name: '指定代表离子', exact: true }).click()
  await network.getByRole('button', { name: '保存图表设置', exact: true }).click()
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText(
    '图表显示设置已加入工作区，请主动保存项目。',
  )
  await page.getByRole('button', { name: '保存项目', exact: true }).first().click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.reload()
  await page.getByRole('link', { name: 'scMM 项目首页' }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '脂质标记验收' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await page.locator('a[href="/preprocess"]').first().click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await expect(page.getByText('40 细胞 × 4 特征 · 每步成功后保留历史层。')).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await page.getByRole('button', { name: '注释与同位素', exact: true }).click()
  await expect(panel).not.toHaveAttribute('open', '')
  await expect(panel.getByRole('heading', { name: '注释与同位素', exact: true })).toBeVisible()
  await expect(panel.getByText('4 / 4 特征 · 4 条候选 · 4 条关系证据')).toBeVisible()
  await expect(network.getByLabel('网络 graph', { exact: true })).toHaveValue('molecule')
  await selectFeature('f_h')
  await expect(panel.getByLabel('指定 LMGP01010001 [M+H]+', { exact: true })).toBeChecked()
  await expect(panel.getByLabel('指定 LMGP01010002 [M+H]+', { exact: true })).not.toBeChecked()
  await expect(panel.getByRole('cell', { name: '接受', exact: true }).first()).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(errors).toEqual([])
})
