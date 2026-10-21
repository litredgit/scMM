import { test, expect, type Page } from './fixtures'
import { readFile } from 'node:fs/promises'

test.use({ actionTimeout: 15000 })

async function create(page: Page, name: string) {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill(name)
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
}
async function importData(page: Page, name: string) {
  await create(page, name)
  await page.getByRole('button', { name: '导入已有结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await page.getByRole('button', { name: '导入结果', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
}
async function noError(page: Page) {
  await expect(page.getByRole('alert')).toHaveCount(0)
}

async function analysisModule(page: Page, id: string, label: string) {
  const select = page.getByRole('combobox', { name: '分析功能', exact: true, includeHidden: true })
  await expect(select).toBeAttached()
  if (await select.isVisible()) await select.selectOption(id)
  else await page.getByRole('button', { name: label, exact: true }).click()
}

test('preprocessing, all analysis panels, precision export and snapshot restore', async ({
  page,
}) => {
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
    .filter({ hasText: 'Vue 全部分析' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await analysisModule(page, 'supervised', '监督与 SHAP')
  await expect(
    page.getByRole('button', { name: '解释当前模型（SHAP）', exact: true }),
  ).toBeDisabled()
  await expect(page.getByRole('combobox', { name: '图例', exact: true })).toHaveValue('hidden')
  await page.getByRole('button', { name: '读取监督诊断', exact: true }).click()
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

test('raw plots, spawned cell preview, detached extraction and explicit review', async ({
  page,
}) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await create(page, 'Vue 原始谱提取')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByLabel('baseline_filter_size', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('feature_snr_threshold', { exact: true })).toBeVisible()
  await expect(page.getByLabel('cell_min_signal', { exact: true })).toHaveValue('100000')
  const panel = page.locator('.raw-parameter-panel')
  expect(await panel.locator('input[type="number"]').count()).toBe(7)
  for (const [label, value] of Object.entries({ ref_mz: '150', mz_min: '140', mz_max: '160' }))
    await page.getByLabel(label, { exact: true }).fill(value)
  await expect(page.getByRole('button', { name: '提取方法：snr说明', exact: true })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'extraction_method' })).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath('raw-compact-1440.png'), fullPage: true })
  for (const width of [700, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
    await expect
      .poll(() =>
        panel.locator('input').evaluateAll((inputs) =>
          inputs.every((input) => {
            const box = input.getBoundingClientRect(),
              parent = input.closest('.raw-parameter-panel')!.getBoundingClientRect()
            return box.width > 0 && box.left >= parent.left && box.right <= parent.right
          }),
        ),
      )
      .toBe(true)
    await page.screenshot({
      path: test.info().outputPath(`raw-compact-${width}.png`),
      fullPage: true,
    })
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('button', { name: '展开全部参数', exact: true }).click()
  await page.getByLabel('reference_ppm_tol', { exact: true }).fill('50')
  await page.getByRole('tab', { name: '细胞与噪声', exact: true }).click()
  await page.getByLabel('baseline_filter_size', { exact: true }).fill('5')
  await page.getByRole('tab', { name: '计算资源', exact: true }).click()
  await page.getByLabel('n_jobs', { exact: true }).fill('1')
  await page.getByRole('tab', { name: '合谱与对齐', exact: true }).click()
  for (const [label, value] of Object.entries({
    ppm_tol: '500',
    resolution: '5000',
    resample_points_per_fwhm: '2',
  }))
    await page.getByLabel(label, { exact: true }).fill(value)
  await page.getByRole('tab', { name: '合谱与对齐', exact: true }).press('ArrowLeft')
  await expect(page.getByRole('tab', { name: '细胞与噪声', exact: true })).toBeFocused()
  await expect(page.getByLabel('baseline_filter_size', { exact: true })).toHaveValue('5')
  await page.getByRole('button', { name: '收起扩展参数', exact: true }).click()
  await page.getByRole('button', { name: '展开全部参数', exact: true }).click()
  await expect(page.getByLabel('baseline_filter_size', { exact: true })).toHaveValue('5')
  await page.getByRole('tab', { name: '合谱与对齐', exact: true }).click()
  await expect(page.getByLabel('resolution', { exact: true })).toHaveValue('5000')
  await page.screenshot({ path: test.info().outputPath('raw-expanded-1440.png'), fullPage: true })
  await page.getByRole('button', { name: '收起扩展参数', exact: true }).click()
  await page.getByRole('button', { name: '应用参数', exact: true }).click()
  await noError(page)
  await page.getByRole('button', { name: '单扫描', exact: true }).click()
  await page.getByRole('button', { name: '下一帧', exact: true }).click()
  await expect(page.getByLabel('scan_index（从 0 开始）', { exact: true })).toHaveValue('1')
  await page.getByLabel('scan time（秒）', { exact: true }).fill('20')
  await page.getByLabel('scan time（秒）', { exact: true }).press('Tab')
  await expect(page.getByLabel('scan_index（从 0 开始）', { exact: true })).toHaveValue('20')
  await page.getByRole('button', { name: 'TIC', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await page.getByRole('button', { name: '预览细胞窗口', exact: true }).click()
  await expect(page.getByText('检出 0 个细胞；预览不会直接建立当前数据。')).toBeVisible({
    timeout: 30000,
  })
  await page.getByLabel('cell_min_signal', { exact: true }).fill('0')
  await page.getByRole('button', { name: '应用参数', exact: true }).click()
  await page.getByRole('button', { name: '预览细胞窗口', exact: true }).click()
  await expect(page.getByText('检出 2 个细胞；预览不会直接建立当前数据。')).toBeVisible({
    timeout: 30000,
  })
  await noError(page)
  await page.getByRole('link', { name: /提取与审核/ }).click()
  await page.getByRole('button', { name: '检查参数与输入', exact: true }).click()
  await expect(page.getByRole('heading', { name: '逐样本完整参数' })).toBeVisible()
  await page.getByRole('button', { name: '开始提取', exact: true }).click()
  await expect(page.getByLabel('extract · 2 细胞', { exact: true })).toBeVisible({ timeout: 30000 })
  await page.getByLabel('extract · 2 细胞', { exact: true }).check()
  await page.getByRole('button', { name: '比较所选成功样本的 QC', exact: true }).click()
  await page.getByRole('button', { name: '建立当前数据集', exact: true }).click()
  await expect(
    page.getByText('当前数据集已建立，可进入预处理。项目仍需主动保存。', { exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '下一步：预处理 →', exact: true }).click()
  await expect(page.getByText('2 细胞 × 1 特征 · 每步成功后保留历史层。')).toBeVisible()
  await noError(page)
  expect(errors).toEqual([])
})

test('saved item plan, protected active project, recycle and restore', async ({ page }) => {
  await create(page, 'Vue 回收恢复')
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页' }).click()
  await page.getByText('管理已保存项目 / 结果', { exact: true }).click()
  const select = page.getByLabel('已保存项目', { exact: true })
  const option = select.locator('option').filter({ hasText: 'Vue 回收恢复' })
  await select.selectOption((await option.getAttribute('value')) as string)
  await page.getByRole('button', { name: '查看快照与缓存保留计划', exact: true }).click()
  const retention = page.locator('[aria-label="快照与缓存保留计划"]')
  await expect(retention).toContainText('当前没有快照或缓存条目。')
  await expect(retention).toContainText('本次释放 0 字节')
  await expect(page.getByRole('button', { name: '移入回收区', exact: true })).toHaveCount(0)
  const retentionDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载只读保留计划', exact: true }).click()
  const advice = JSON.parse(await readFile((await (await retentionDownload).path())!, 'utf8'))
  expect(advice.read_only).toBe(true)
  expect(advice.immediate_freed_bytes).toBe(0)
  expect(advice.token).toBeUndefined()
  expect(advice.items).toEqual([])
  await expect(option).toBeAttached()
  await page.getByRole('button', { name: '查看项目删除计划', exact: true }).click()
  await page.getByRole('button', { name: '移入回收区', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('所选内容已移入共享回收区。')
  await expect(retention).toHaveCount(0)
  await page.getByText('共享回收区（1）', { exact: true }).click()
  await page.getByRole('button', { name: '恢复', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('已恢复到原位置。')
  await expect(page.getByRole('row').filter({ hasText: 'Vue 回收恢复' })).toBeVisible()
  await noError(page)
})

test('latest result preselection, detailed help, stable QC and readable narrow layout', async ({
  page,
}) => {
  test.setTimeout(60000)
  await create(page, '界面说明与默认结果')
  await page.getByRole('button', { name: '导入已有结果', exact: true }).click()
  const listing = await page.request.get('/api/v1/storage/entries?root=Results&kind=results')
  const latest = (await listing.json()).latest.name as string
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await expect(page.getByText(`已选结果：${latest}`, { exact: true })).toBeVisible()
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await expect(page.getByText('已选结果：analysis.h5ad', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toHaveCount(0)
  await page.getByRole('button', { name: '导入结果', exact: true }).click()
  await page.getByRole('link', { name: /预处理/ }).click()
  const helper = page.getByRole('button', { name: 'min_detected说明', exact: true })
  await helper.hover()
  await expect(page.getByRole('tooltip')).toContainText('等于阈值保留')
  await expect(page.getByRole('tooltip')).toContainText('不重做峰检出')
  await helper.focus()
  await expect(page.getByRole('tooltip')).toBeVisible()
  await helper.press('Escape')
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  await page.getByLabel('下一项操作', { exact: true }).selectOption('normalize')
  await page.getByText('查看全部 normalization 方法', { exact: true }).click()
  await expect(page.locator('.method-list .help-trigger')).toHaveCount(7)
  await page.getByLabel('normalization', { exact: true }).selectOption('log')
  await expect(page.locator('.method-help > p')).toContainText('零值变为')
  await page.getByLabel('normalization', { exact: true }).selectOption('total')
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  await expect(page.getByText(/横轴采用稳定范围/)).toBeVisible()
  await expect
    .poll(() =>
      page
        .locator('.js-plotly-plot')
        .first()
        .evaluate(
          (el) =>
            (el as HTMLElement & { _fullLayout: { xaxis: { range: number[] } } })._fullLayout.xaxis
              .range,
        ),
    )
    .toEqual([0.95, 1.05])
  expect(await page.evaluate(() => getComputedStyle(document.body).fontSize)).toBe('16px')
  const plotSize = await page
    .locator('.js-plotly-plot')
    .first()
    .evaluate((el) => ({ width: el.clientWidth, height: el.clientHeight }))
  for (const format of ['SVG', 'PNG']) {
    const wait = page.waitForEvent('download')
    await page.getByRole('button', { name: `下载 ${format}`, exact: true }).click()
    const download = await wait
    const bytes = await readFile((await download.path())!)
    if (format === 'PNG') {
      expect(bytes.readUInt32BE(16)).toBe(Math.floor((89 / 25.4) * 300))
      expect(bytes.readUInt32BE(20)).toBe(Math.floor((65 / 25.4) * 300))
    } else {
      const svg = bytes.toString('utf8')
      const width = Number(svg.match(/<svg[^>]* width="([\d.]+)"/)?.[1])
      const height = Number(svg.match(/<svg[^>]* height="([\d.]+)"/)?.[1])
      expect(width / height).toBeCloseTo(89 / 65, 2)
    }
  }

  await page.screenshot({ path: test.info().outputPath('preprocess-1440.png'), fullPage: true })
  for (const width of [700, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true)
    await expect
      .poll(() =>
        page
          .locator('.js-plotly-plot')
          .first()
          .evaluate(
            (el) =>
              Math.abs(
                el.getBoundingClientRect().width -
                  (el as HTMLElement & { _fullLayout: { width: number } })._fullLayout.width,
              ) < 2,
          ),
      )
      .toBe(true)
    await page.screenshot({
      path: test.info().outputPath(`preprocess-${width}.png`),
      fullPage: true,
    })
  }
  await noError(page)
})
