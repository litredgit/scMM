import { test, expect, type Page } from './fixtures'
import { createProject as create } from './support/project'

test.use({ actionTimeout: 15000 })

async function noError(page: Page) {
  await expect(page.getByRole('alert')).toHaveCount(0)
}

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

test('two completed batches compare without replacing data, link signal axes and recycle an unused batch', async ({
  page,
}) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await page
    .getByRole('row')
    .filter({ hasText: '两批次比较合成项目' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await page.getByRole('link', { name: /提取与审核/ }).click()
  const panel = page.locator('.batch-comparison')
  await panel.locator(':scope > summary').click()
  const compared = page.waitForResponse((r) => r.url().endsWith('/extraction/compare'))
  await panel.getByRole('button', { name: '比较两个批次', exact: true }).click()
  const response = await compared
  expect(response.ok()).toBeTruthy()
  const result = await response.json()
  expect(result.samples[0].input).toBe('same')
  expect(result.samples[0].name_A).toBe('中文样本')
  expect(result.export_tables.cells).toContain('中文样本')
  expect(
    result.parameters.some(
      (row: { parameter: string; changed: boolean }) => row.parameter === 'cell_snr' && row.changed,
    ),
  ).toBe(true)
  await expect(panel.getByText('相同输入身份', { exact: true }).first()).toBeVisible()
  await expect(panel.locator('.js-plotly-plot')).toHaveCount(2)
  await panel.getByRole('button', { name: '并排查看两批信号', exact: true }).click()
  const signals = panel.locator('.comparison-signals .js-plotly-plot')
  await expect(signals).toHaveCount(2)
  await signals.first().evaluate((el) => {
    const graph = el as HTMLElement & {
      layout: {
        xaxis: { range: number[]; autorange: boolean }
        xaxis2: { range: number[]; autorange: boolean }
      }
      emit: (name: string, value: unknown) => void
    }
    graph.layout.xaxis.range = [5, 15]
    graph.layout.xaxis.autorange = false
    graph.layout.xaxis2.range = [5, 15]
    graph.layout.xaxis2.autorange = false
    graph.emit('plotly_relayout', { 'xaxis.range': [5, 15], 'xaxis2.range': [5, 15] })
  })
  await expect
    .poll(() =>
      signals
        .last()
        .evaluate(
          (el) =>
            (el as HTMLElement & { layout: { xaxis: { range: number[] } } }).layout.xaxis.range,
        ),
    )
    .toEqual([5, 15])
  const download = page.waitForEvent('download')
  await panel.getByRole('button', { name: '下载完整细胞 QC对比 CSV', exact: true }).click()
  expect((await download).suggestedFilename()).toBe('batch-comparison-cells.csv')
  await page.screenshot({ path: test.info().outputPath('batch-comparison.png'), fullPage: true })
  await panel.locator(':scope > summary').click()
  await page.getByRole('button', { name: '移入回收站', exact: true }).click()
  await expect(page.getByRole('button', { name: '执行移入回收站', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '执行移入回收站', exact: true }).click()
  await expect(
    page.getByLabel('处理批次', { exact: true }).locator('option:not([value=""])'),
  ).toHaveCount(1)
  await noError(page)
  expect(errors).toEqual([])
})
