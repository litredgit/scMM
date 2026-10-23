import { test, expect, type Page } from './fixtures'
import { readFile } from 'node:fs/promises'
import { createProject as create, importDataset as importData } from './support/project'
import { serialPolling } from '../src/api/polling'
import type { useWorkspace } from '../src/stores/workspace'

test.use({ actionTimeout: 15000 })

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
  const validationNotes = page.getByRole('complementary', { name: '监督验证解释', exact: true })
  await expect(validationNotes).toContainText('细胞数不等于生物重复')
  await expect(validationNotes).toContainText('不再是独立测试')
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
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await analysisModule(page, 'supervised', '监督与 SHAP')
  await expect(
    page.getByRole('button', { name: '解释当前模型（SHAP）', exact: true }),
  ).toBeDisabled()
  await expect(page.getByRole('combobox', { name: '图例', exact: true })).toHaveValue('hidden')
  await page.getByRole('button', { name: '读取监督诊断', exact: true }).click()
  await expect(validationNotes).toContainText('细胞数不等于生物重复')
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
  expect(advice.selected_bytes).toBe(0)
  expect(advice.policy_parameters).toEqual({ min_age_days: null, keep_latest: null })
  await page.getByLabel('最小年龄（天）', { exact: true }).fill('30')
  await expect(retention).toHaveCount(0)
  await page.getByLabel('每类至少保留最新数量', { exact: true }).fill('2')
  await page.getByRole('button', { name: '查看快照与缓存保留计划', exact: true }).click()
  const policyDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载只读保留计划', exact: true }).click()
  const policy = JSON.parse(await readFile((await (await policyDownload).path())!, 'utf8'))
  expect(policy.policy_parameters).toEqual({ min_age_days: 30, keep_latest: 2 })
  expect(policy.read_only).toBe(true)
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

test('reviewed retention cleanup archives a shared pair and restores it', async ({ page }) => {
  await page.goto('/')
  await page.getByText('管理已保存项目 / 结果', { exact: true }).click()
  const selected = page.getByLabel('已保存项目', { exact: true })
  const option = selected.locator('option').filter({ hasText: '策略配对缓存合成项目' })
  await selected.selectOption((await option.getAttribute('value'))!)
  await page.getByLabel('每类至少保留最新数量', { exact: true }).fill('0')
  await page.getByRole('button', { name: '查看快照与缓存保留计划', exact: true }).click()
  const retention = page.locator('[aria-label="快照与缓存保留计划"]')
  await expect(retention).toContainText('共同特征缓存')
  await expect(page.getByRole('button', { name: '将策略清单移入回收区', exact: true })).toHaveCount(
    0,
  )
  await page.getByRole('button', { name: '查看策略清理执行计划', exact: true }).click()
  const plan = page.locator('[aria-label="策略清理执行计划"]')
  await expect(plan).toContainText('2 文件')
  await expect(plan).toContainText('.npy')
  await expect(plan).toContainText('.json')
  await page.getByLabel('每类至少保留最新数量', { exact: true }).fill('1')
  await expect(plan).toHaveCount(0)
  await page.getByLabel('每类至少保留最新数量', { exact: true }).fill('0')
  await page.getByRole('button', { name: '查看快照与缓存保留计划', exact: true }).click()
  await page.getByRole('button', { name: '查看策略清理执行计划', exact: true }).click()
  await page.getByRole('button', { name: '将策略清单移入回收区', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('策略清单已移入共享回收区，尚未释放磁盘空间。')
  await page.getByRole('button', { name: '查看快照与缓存保留计划', exact: true }).click()
  await expect(retention).toContainText('当前没有快照或缓存条目。')
  await page.getByText(/^共享回收区（/).click()
  const entry = page.getByRole('row').filter({ hasText: '快照与缓存策略清理' })
  await entry.getByRole('button', { name: '恢复', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('已恢复到原位置。')
  await page.getByRole('button', { name: '查看快照与缓存保留计划', exact: true }).click()
  await expect(retention).toContainText('共同特征缓存')
  await expect(entry).toHaveCount(0)
})

test('automatic retention rules require review, survive refresh and stop explicitly', async ({
  page,
}) => {
  await create(page, 'Vue 自动保留规则')
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页' }).click()
  const selectProject = async () => {
    await page.getByText('管理已保存项目 / 结果', { exact: true }).click()
    const selected = page.getByLabel('已保存项目', { exact: true })
    const option = selected.locator('option').filter({ hasText: 'Vue 自动保留规则' })
    await selected.selectOption((await option.getAttribute('value'))!)
    await page.getByText('持续自动保留（默认关闭）', { exact: true }).click()
  }
  await selectProject()
  const state = page.locator('[aria-label="自动保留状态"]')
  await expect(state).toContainText('已停用 / 尚未设置')
  await page.getByLabel('每类至少保留最新数量', { exact: true }).fill('0')
  await page.getByLabel('自动保留检查间隔（分钟）', { exact: true }).fill('1')
  await page.getByRole('button', { name: '审阅自动保留规则', exact: true }).click()
  const review = page.locator('[aria-label="自动保留规则审阅"]')
  await expect(review).toContainText('未来符合条件的产物')
  await expect(page.locator('[aria-label="快照与缓存保留计划"]')).toContainText(
    '当前没有快照或缓存条目。',
  )
  await page.getByLabel('自动保留检查间隔（分钟）', { exact: true }).fill('2')
  await expect(review).toHaveCount(0)
  await page.getByRole('button', { name: '审阅自动保留规则', exact: true }).click()
  await page.getByRole('button', { name: '启用持续自动保留', exact: true }).click()
  await expect(state).toContainText('已启用 · 每 2 分钟检查')
  await expect(state).toContainText('每类保留最新 0 项')
  await page.reload()
  await selectProject()
  await expect(state).toContainText('已启用 · 每 2 分钟检查')
  await page.getByRole('button', { name: '停用自动保留', exact: true }).click()
  await expect(state).toContainText('已停用 / 尚未设置')
  await expect(page.getByRole('status')).toContainText('已停用自动保留')
})

test('explicit result selection, detailed help, stable QC and readable narrow layout', async ({
  page,
}) => {
  test.setTimeout(60000)
  await create(page, '界面说明与默认结果')
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  const listing = await page.request.get('/api/v1/storage/entries?root=Results&kind=results')
  const latest = (await listing.json()).latest.name as string
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await expect(page.getByText(`已选结果：${latest}`, { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导入并替换当前数据', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await expect(page.getByText('已选结果：analysis.h5ad', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toHaveCount(0)
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
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

test('current report downloads contain a PDF and portable numeric attachments', async ({
  page,
}) => {
  await importData(page, '当前报告导出')
  await page.getByRole('link', { name: /结果与保存/ }).click()
  await page.getByLabel('下载内容', { exact: true }).selectOption('quality_pdf')
  await expect(page.getByLabel('下载文件名', { exact: true })).toHaveValue('current_qc.pdf')
  const pdfDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载完整结果', exact: true }).click()
  const pdf = await pdfDownload
  expect(pdf.suggestedFilename()).toBe('current_qc.pdf')
  expect((await readFile((await pdf.path())!)).subarray(0, 5).toString()).toBe('%PDF-')
  await page.getByLabel('下载内容', { exact: true }).selectOption('report_zip')
  const zipDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载完整结果', exact: true }).click()
  const zip = await zipDownload
  expect(zip.suggestedFilename()).toBe('current_analysis_report.zip')
  expect((await readFile((await zip.path())!)).subarray(0, 2).toString()).toBe('PK')
  await noError(page)
})

test('raw signal diagnostic stays independent and exports full numeric comparisons', async ({
  page,
}) => {
  await create(page, '独立原始诊断')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
  await page.locator('summary').filter({ hasText: '独立原始信号诊断' }).click()
  const run = page.getByRole('button', { name: '运行独立诊断', exact: true })
  await expect(run).toBeDisabled()
  await page.getByLabel('诊断信号', { exact: true }).selectOption('eic')
  await page.getByLabel('诊断参考离子', { exact: true }).fill('150,151')
  await page.getByLabel('诊断基线', { exact: true }).selectOption('median')
  await expect(run).toBeDisabled()
  await page.getByLabel('诊断基线窗口', { exact: true }).fill('5')
  const response = page.waitForResponse(
    (r) => r.url().endsWith('/raw/diagnostic') && r.request().method() === 'POST',
  )
  await run.click()
  const body = (await (await response).json()).value
  expect(body.figure.layout.meta.parameters.baseline).toBe('median')
  expect(body.table.total).toBe(62)
  expect(body.figure.layout.meta.export_tables['diagnostic.csv']).toContain('rank_residual')
  await expect(page.getByText('迭代噪声估计与残差标准差不同', { exact: false })).toBeVisible()
  await expect(page.getByLabel('cell_min_signal', { exact: true })).toHaveValue('100000')
  const panel = page.locator('details.card').filter({ hasText: '独立原始信号诊断' })
  await expect(panel.locator('.js-plotly-plot')).toBeVisible()
  await page.route('**/workspace/raw/diagnostic', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 400, json: { error: { message: '同参数重算失败' } } })
      : route.continue(),
  )
  await run.click()
  await expect(page.getByRole('alert')).toContainText('同参数重算失败')
  await expect(panel.locator('.js-plotly-plot')).toBeVisible()
  await page.unroute('**/workspace/raw/diagnostic')
  await page.getByRole('button', { name: '清除错误', exact: true }).click()
  const download = page.waitForEvent('download')
  await panel.getByRole('button', { name: '下载作图数据', exact: true }).click()
  expect((await download).suggestedFilename()).toMatch(/\.zip$/)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '独立原始诊断' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  // Restored read-only plots remain available without rerunning raw computation.
  if (!(await page.getByLabel('诊断基线', { exact: true }).isVisible()))
    await page.locator('summary').filter({ hasText: '独立原始信号诊断' }).click()
  await expect(page.getByLabel('诊断基线窗口', { exact: true })).toHaveValue('5')
  await expect(panel.locator('.js-plotly-plot')).toBeVisible()
  await page.getByLabel('诊断基线', { exact: true }).selectOption('zero')
  await expect(panel.locator('.js-plotly-plot')).toHaveCount(0)
  await noError(page)
})

for (const mode of ['hidden-error', 'resumed-error', 'hidden-ready'] as const) {
  test(`preview polling ignores previous page activation: ${mode}`, async ({ page }) => {
    await create(page, '预览页面停用')
    await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
    await page.getByRole('button', { name: /extract.mzML/ }).click()
    await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
    await page.getByRole('link', { name: /原始谱与参数/ }).click()
    await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let entered!: () => void
    const pending = new Promise<void>((resolve) => {
      entered = resolve
    })
    let reads = 0
    let revision = 0
    let collects = 0
    await page.route('**/workspace/raw/preview/collect', async (route) => {
      collects++
      await route.fulfill({ status: 400, json: { error: { message: '不应收集停用代次' } } })
    })
    await page.route('**/workspace/raw/preview', async (route) => {
      if (route.request().method() === 'POST') {
        const response = await page.request.get('/api/v1/workspace', {
          headers: route.request().headers(),
        })
        const workspace = await response.json()
        revision = workspace.revision
        await route.fulfill({
          json: {
            workspace,
            value: {
              id: 'synthetic-poll',
              revision: workspace.revision,
              status: 'running',
              message: '轮询测试',
            },
          },
        })
      } else {
        reads++
        entered()
        await held
        await route.fulfill(
          mode === 'hidden-ready'
            ? { json: { id: 'synthetic-poll', revision, status: 'ready', message: '旧代次可收集' } }
            : { status: 400, json: { error: { message: '停用页面的迟到状态错误' } } },
        )
      }
    })
    await page.getByRole('button', { name: '预览细胞窗口', exact: true }).click()
    await pending
    await page.getByRole('link', { name: /项目与样本/ }).click()
    if (mode === 'resumed-error') {
      await page.getByRole('link', { name: /原始谱与参数/ }).click()
      // Longer than the 1500ms cadence: activation must not overlap a held read.
      await page.waitForTimeout(1700)
      expect(reads).toBe(1)
    }
    const response = page.waitForResponse(
      (r) => r.url().endsWith('/raw/preview') && r.request().method() === 'GET',
    )
    release()
    await response
    await page.waitForTimeout(100)
    expect(collects).toBe(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}

test('serial polling coalesces refreshes and resume waits for the old read to settle', async () => {
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let calls = 0
  let concurrent = 0
  let maximum = 0
  const publications: boolean[] = []
  const polling = serialPolling(
    async (isCurrent) => {
      calls++
      concurrent++
      maximum = Math.max(maximum, concurrent)
      if (calls === 1) await held
      publications.push(isCurrent())
      concurrent--
    },
    60_000,
    (cause) => {
      throw cause
    },
  )
  try {
    polling.start()
    await expect.poll(() => calls).toBe(1)
    const first = polling.refresh()
    expect(polling.refresh()).toBe(first)
    polling.stop()
    polling.start()
    expect(calls).toBe(1)
    release()
    await first
    await expect.poll(() => calls).toBe(2)
    expect(maximum).toBe(1)
    expect(publications).toEqual([false, true])
  } finally {
    release()
    polling.stop()
  }
})

test('serial polling reports current errors once and can read again without replaying a write', async () => {
  const errors: unknown[] = []
  let calls = 0
  const polling = serialPolling(
    async () => {
      calls++
      if (calls === 1) throw new Error('合成读取失败')
    },
    60_000,
    (cause) => errors.push(cause),
  )
  try {
    polling.start(false)
    await polling.refresh()
    expect(errors).toHaveLength(1)
    await polling.refresh()
    expect(calls).toBe(2)
    expect(errors).toHaveLength(1)
  } finally {
    polling.stop()
  }
})

test('stopping before a poll starts prevents the request and stale failures are ignored', async () => {
  const errors: unknown[] = []
  let calls = 0
  let reject!: (cause: unknown) => void
  const held = new Promise<void>((_, fail) => {
    reject = fail
  })
  const polling = serialPolling(
    async () => {
      calls++
      await held
    },
    60_000,
    (cause) => errors.push(cause),
  )
  polling.start()
  polling.stop()
  await Promise.resolve()
  expect(calls).toBe(0)
  polling.start()
  await expect.poll(() => calls).toBe(1)
  const pending = polling.refresh()
  polling.stop()
  reject(new Error('停用后的失败'))
  await pending
  expect(errors).toEqual([])
})

test('duplicate extraction review cannot report success or clear the running phase before the request finishes', async ({
  page,
}) => {
  await page.route('**/workspace/extraction/batches', (route) =>
    route.fulfill({
      json: [
        {
          path: '/synthetic/batch/state',
          status: 'completed',
          created_at: '2026-10-22T00:00:00Z',
          message: '合成批次',
          samples: [
            { id: 'synthetic-a', name: '待审核输入', status: 'succeeded', cells: 2, features: 1 },
          ],
        },
      ],
    }),
  )
  await create(page, '重复审核操作')
  await page.getByRole('link', { name: /提取与审核/ }).click()
  await page.getByLabel('待审核输入 · 2 细胞', { exact: true }).check()
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const pending = new Promise<void>((resolve) => {
    entered = resolve
  })
  let requests = 0
  await page.route('**/workspace/extraction/review', async (route) => {
    requests++
    entered()
    await held
    await route.fulfill({ status: 400, json: { error: { message: '合成审核失败，未建立数据' } } })
  })
  try {
    await page.getByRole('button', { name: '建立当前数据集', exact: true }).evaluate((button) => {
      // Two already queued events before Vue patches disabled must share the same guard.
      ;(button as HTMLButtonElement).click()
      ;(button as HTMLButtonElement).click()
    })
    await pending
    expect(requests).toBe(1)
    await expect(
      page.getByText('当前数据集已建立，可进入预处理。项目仍需主动保存。', { exact: true }),
    ).toHaveCount(0)
    await expect(page.getByText('正在合并所选样本并建立当前数据集…', { exact: true })).toBeVisible()
    release()
    await expect(page.getByRole('alert')).toContainText('合成审核失败，未建立数据')
    await expect(
      page.getByText('当前数据集已建立，可进入预处理。项目仍需主动保存。', { exact: true }),
    ).toHaveCount(0)
  } finally {
    release()
  }
})

test('a delayed background read cannot overwrite the failure of a later save', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const pending = new Promise<void>((resolve) => {
    entered = resolve
  })
  await page.route('**/workspace/extraction/batches', async (route) => {
    entered()
    await held
    await route.fulfill({ status: 400, json: { error: { message: '旧的后台读取失败' } } })
  })
  await page.route('**/workspace/project/save', (route) =>
    route.fulfill({ status: 400, json: { error: { message: '本次项目保存失败' } } }),
  )
  try {
    await create(page, '操作反馈归属')
    await pending
    await page.getByRole('button', { name: '保存项目', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('本次项目保存失败')
    const response = page.waitForResponse((r) => r.url().endsWith('/extraction/batches'))
    release()
    await response
    await page.waitForTimeout(100)
    await expect(page.getByRole('alert')).toContainText('本次项目保存失败')
    await expect(page.getByRole('alert')).not.toContainText('旧的后台读取失败')
  } finally {
    release()
  }
})

test('opening raw data keeps one operation through scan lookup and both initial plots', async ({
  page,
}) => {
  await create(page, '原始打开完整操作链')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const pending = new Promise<void>((resolve) => {
    entered = resolve
  })
  let opens = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/raw/open')) opens++
  })
  await page.route('**/workspace/raw/scans?*', async (route) => {
    entered()
    await held
    await route.continue()
  })
  try {
    const button = page.getByRole('button', { name: '打开原始文件', exact: true })
    await button.click()
    await pending
    await expect(button).toBeDisabled()
    await expect(
      page.locator('.task-note').filter({ hasText: '打开原始文件：刷新状态中' }),
    ).toBeVisible()
    const navigation = page.getByRole('navigation', { name: '步骤切换', exact: true })
    await navigation.getByRole('button', { name: /上一步：项目与样本/ }).click()
    await expect(page).toHaveURL(/\/samples$/)
    await navigation.getByRole('button', { name: /下一步：原始谱与参数/ }).click()
    await expect(button).toBeDisabled()
    await button.evaluate((element) => (element as HTMLButtonElement).click())
    expect(opens).toBe(1)
    const plotted = page.waitForResponse(
      (r) => r.url().endsWith('/raw/plot') && r.request().postDataJSON()?.kind === 'single',
    )
    release()
    await plotted
    await expect(button).toBeEnabled()
    await expect(page.locator('.js-plotly-plot')).toBeVisible()
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally {
    release()
  }
})

test('failed clearing of a sample exception keeps the raw plot and unsaved parameter draft', async ({
  page,
}) => {
  await create(page, '例外清除失败')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await page.getByLabel('cell_min_signal', { exact: true }).fill('42')
  await page.route('**/workspace/parameters/clear', (route) =>
    route.fulfill({ status: 400, json: { error: { message: '合成例外清除失败' } } }),
  )
  await page.getByRole('button', { name: '清除样本例外', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('合成例外清除失败')
  await expect(page.getByLabel('cell_min_signal', { exact: true })).toHaveValue('42')
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
})

test('operation outcomes distinguish skipped, stale, failed and void success without releasing a newer operation', async ({
  page,
}) => {
  await create(page, '操作返回语义')
  const result = await page.evaluate(async () => {
    // Access the running Pinia store to exercise its public action contract.
    const root = document.getElementById('app') as HTMLElement & {
      __vue_app__: {
        config: {
          globalProperties: { $pinia: { _s: Map<string, ReturnType<typeof useWorkspace>> } }
        }
      }
    }
    const store = root.__vue_app__.config.globalProperties.$pinia._s.get('workspace')!
    let releaseOld!: () => void
    const oldGate = new Promise<void>((resolve) => {
      releaseOld = resolve
    })
    const old = store.run(async (scope) => {
      await oldGate
      scope.update({ label: '旧操作不得发布', phase: 'failed' })
      return '旧值'
    }, '旧成功不得发布')
    let submitted = 0
    const skipped = await store.run(async () => {
      submitted++
      return '重复操作'
    })
    store.reset()
    let releaseNew!: () => void
    const newGate = new Promise<void>((resolve) => {
      releaseNew = resolve
    })
    const newer = store.run(async (scope) => {
      scope.update({ label: '新操作', phase: 'collecting' })
      await newGate
      return '新值'
    }, '新操作成功')
    releaseOld()
    const stale = await old
    const whileNew = {
      busy: store.busy,
      label: store.operation?.label,
      phase: store.operation?.phase,
      notice: store.notice,
      error: store.error,
    }
    releaseNew()
    const succeeded = await newer
    const successNotice = store.notice
    const failed = await store.run(async () => {
      throw new Error('当前操作失败')
    }, '不得发布的成功')
    const failure = {
      busy: store.busy,
      phase: store.operation?.phase,
      error: store.error,
      notice: store.notice,
    }
    const empty = await store.run(async () => undefined)
    return {
      submitted,
      skipped,
      stale,
      whileNew,
      succeeded,
      successNotice,
      failed,
      failure,
      emptyStatus: empty.status,
    }
  })
  expect(result.submitted).toBe(0)
  expect(result.skipped.status).toBe('skipped')
  expect(result.stale.status).toBe('stale')
  expect(result.whileNew).toEqual({
    busy: true,
    label: '新操作',
    phase: 'collecting',
    notice: '',
    error: '',
  })
  expect(result.succeeded).toEqual({ status: 'succeeded', value: '新值' })
  expect(result.successNotice).toBe('新操作成功')
  expect(result.failed).toEqual({ status: 'failed', error: '当前操作失败' })
  expect(result.failure).toEqual({
    busy: false,
    phase: 'failed',
    error: '当前操作失败',
    notice: '',
  })
  expect(result.emptyStatus).toBe('succeeded')
})

test('changing the raw sample clears counts and messages belonging to the previous preview', async ({
  page,
}) => {
  await create(page, '预览来源切换')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: /alpha.mzML/ }).click()
  await page.getByRole('button', { name: '添加 2 个文件', exact: true }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  let revision = 0
  await page.route('**/workspace/raw/preview', async (route) => {
    if (route.request().method() === 'POST') {
      const response = await page.request.get('/api/v1/workspace', {
        headers: route.request().headers(),
      })
      const workspace = await response.json()
      revision = workspace.revision
      await route.fulfill({
        json: {
          workspace,
          value: { id: 'scope-preview', revision, status: 'running', message: '合成预览' },
        },
      })
    } else
      await route.fulfill({
        json: { id: 'scope-preview', revision, status: 'ready', message: '可收集' },
      })
  })
  await page.route('**/workspace/raw/preview/collect', async (route) => {
    const headers = route.request().headers()
    const [current, parameters] = await Promise.all([
      page.request.get('/api/v1/workspace', { headers }),
      page.request.get('/api/v1/workspace/parameters', { headers }),
    ])
    await route.fulfill({
      json: {
        workspace: await current.json(),
        value: {
          parameters: await parameters.json(),
          figure: { data: [], layout: {} },
          table: { columns: [], rows: [], total: 0 },
          cell_count: 7,
          reused: false,
        },
      },
    })
  })
  await page.getByRole('button', { name: '预览细胞窗口', exact: true }).click()
  await expect(
    page.getByText('检出 7 个细胞；预览不会直接建立当前数据。', { exact: true }),
  ).toBeVisible()
  await page.getByLabel('当前样本', { exact: true }).selectOption({ label: 'alpha' })
  await expect(
    page.getByText('检出 7 个细胞；预览不会直接建立当前数据。', { exact: true }),
  ).toHaveCount(0)
  await expect(page.getByText(/预览完成，7 个细胞/)).toHaveCount(0)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

for (const waitAt of ['response', 'blob'] as const) {
  test(`a previous workspace download cannot publish after reset while waiting for ${waitAt}`, async ({
    page,
  }) => {
    await create(page, `下载来源-${waitAt}`)
    let entered!: () => void
    const pending = new Promise<void>((resolve) => {
      entered = resolve
    })
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let downloads = 0
    page.on('download', () => {
      downloads++
    })
    if (waitAt === 'blob') {
      await page.exposeFunction('scmmTestBlobRead', () => entered())
      await page.evaluate(() => {
        const original = Response.prototype.blob
        Response.prototype.blob = async function () {
          if (this.url.includes('/workspace/results/download')) {
            const continued = new Promise<void>((resolve) =>
              window.addEventListener('scmm-test-continue-blob', () => resolve(), { once: true }),
            )
            await (window as unknown as { scmmTestBlobRead(): Promise<void> }).scmmTestBlobRead()
            await continued
          }
          return original.call(this)
        }
      })
    }
    await page.route('**/workspace/results/download?*', async (route) => {
      if (waitAt === 'response') {
        entered()
        await held
      }
      await route.fulfill({
        contentType: 'text/csv',
        body: 'feature,value\nf0,1.123456789012345\n',
      })
    })
    const result = page.evaluate(async () => {
      const root = document.getElementById('app') as HTMLElement & {
        __vue_app__: {
          config: {
            globalProperties: { $pinia: { _s: Map<string, ReturnType<typeof useWorkspace>> } }
          }
        }
      }
      return root.__vue_app__.config.globalProperties.$pinia._s
        .get('workspace')!
        .download('matrix', 'late.csv')
    })
    try {
      await pending
      await page.evaluate(() => {
        const root = document.getElementById('app') as HTMLElement & {
          __vue_app__: {
            config: {
              globalProperties: { $pinia: { _s: Map<string, ReturnType<typeof useWorkspace>> } }
            }
          }
        }
        root.__vue_app__.config.globalProperties.$pinia._s.get('workspace')!.reset()
        window.dispatchEvent(new Event('scmm-test-continue-blob'))
      })
      release()
      expect((await result)?.status).toBe('stale')
      expect(downloads).toBe(0)
      await expect(page.getByRole('alert')).toHaveCount(0)
    } finally {
      release()
    }
  })
}
