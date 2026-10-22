import { test, expect, type Page } from './fixtures'
import { readFile } from 'node:fs/promises'

let pageErrors: string[] = []
test.beforeEach(async ({ page }) => {
  pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
})
test.afterEach(() => expect(pageErrors).toEqual([]))

async function importAnalysis(page: Page, name: string, filename = 'analysis.h5ad') {
  if (page.url() === 'about:blank') await page.goto('/')
  else await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page.getByLabel('项目名称', { exact: true }).fill(name)
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page
    .getByRole('button', { name: new RegExp(`^(?:▤ )?${filename.replaceAll('.', '[.]')}\\s`) })
    .click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await expect(page.getByLabel('group_key', { exact: true }).first()).toBeAttached()
}
async function module(page: Page, name: string) {
  await page.getByRole('button', { name, exact: true }).click()
}

test('heatmap selected sample order, pending settings and Cell SVG use one export path', async ({
  page,
}) => {
  test.setTimeout(60000)
  await importAnalysis(page, '热图范围与论文导出')
  await module(page, '热图')
  const panel = page
    .locator('.analysis-module-split')
    .filter({ has: page.getByRole('heading', { name: '特征热图', exact: true }) })
  await panel.getByLabel('特征编号（换行或逗号分隔）').fill('f0\nf1')
  await panel.getByText('样本 · 全部', { exact: true }).click()
  await panel.getByRole('button', { name: '清空样本', exact: true }).click()
  await panel.getByLabel('作图样本 s1', { exact: true }).check()
  await panel.getByLabel('作图样本 s0', { exact: true }).check()
  await panel.getByText('组别 · 全部', { exact: true }).click()
  await panel.getByRole('button', { name: '清空组别', exact: true }).click()
  await panel.getByLabel('作图组别 a', { exact: true }).check()
  const plotted = page.waitForResponse(
    (r) => r.url().endsWith('/analysis/plot') && r.request().postDataJSON().kind === 'heatmap',
  )
  await panel.getByRole('button', { name: '生成热图', exact: true }).click()
  const response = await plotted
  expect(response.ok()).toBeTruthy()
  const figure = (await response.json()).value
  expect(figure.layout.meta.column_order).toEqual([
    ...Array.from({ length: 8 }, (_, i) => `c${i + 8}`),
    ...Array.from({ length: 8 }, (_, i) => `c${i}`),
  ])
  await panel.getByLabel('热图色阶下限').fill('-2')
  await panel.getByLabel('热图色阶上限').fill('2')
  await expect(panel.getByRole('status').filter({ hasText: '设置已编辑' })).toBeVisible()
  await panel.getByRole('button', { name: '生成热图', exact: true }).click()
  const plot = panel.locator('.plot-shell')
  await plot.locator('.plot-settings summary').click()
  await plot.getByLabel('论文规格', { exact: true }).selectOption('cell-single')
  await expect(plot.getByLabel('宽度（mm）', { exact: true })).toHaveValue('85')
  await expect(plot.getByLabel('图内显示标题', { exact: true })).not.toBeChecked()
  await expect(plot.getByRole('option', { name: /Analytical Chemistry/ })).toHaveCount(0)
  await plot.getByRole('button', { name: '预览导出效果', exact: true }).click()
  await expect(plot.getByAltText('按论文设置生成的导出预览')).toBeVisible()
  const direct = page.waitForEvent('download')
  await plot.getByRole('button', { name: '下载 SVG', exact: true }).click()
  const directSvg = await readFile((await (await direct).path())!, 'utf8')
  expect(directSvg).toContain('Arial')
  expect(directSvg).not.toContain('Feature heatmap')
  const toolbar = page.waitForEvent('download')
  await plot.locator('.plot').hover()
  await plot.locator('[data-title="下载论文 SVG"]').click()
  const toolbarSvg = await readFile((await (await toolbar).path())!, 'utf8')
  expect(toolbarSvg).toContain('Arial')
  const images = (svg: string) => svg.match(/data:image\/png;base64,[^"]+/g) ?? []
  expect(images(directSvg).length).toBeGreaterThan(0)
  expect(images(toolbarSvg)).toEqual(images(directSvg))
  await page.screenshot({ path: test.info().outputPath('heatmap-cell-export.png'), fullPage: true })
})

test('legacy settings, independent parameters, draft and project reset, narrow panels', async ({
  page,
}) => {
  let legacy = true
  await page.route('**/workspace/analysis', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    if (legacy)
      body.settings = {
        reduction: { random_state: 73, store_key: 'X_old', scale: true },
        diff: { layer: 'scmm_input_0' },
        colorSource: 'feature',
        color: 'feature:f0',
        latentKey: 'X_old_latent',
        usePca: false,
      }
    await route.fulfill({ response, json: body })
  })
  await importAnalysis(page, '分析设置迁移')
  await expect(page.getByLabel('store_key', { exact: true })).toHaveValue('X_old')
  await expect(page.getByLabel('Color', { exact: true })).toHaveValue('feature:f0')
  await module(page, '监督与 SHAP')
  await expect(page.getByRole('button', { name: '监督与 SHAP', exact: true })).toHaveCSS(
    'background-color',
    'rgb(239, 246, 255)',
  )
  await expect(
    page.getByLabel('random_state', { exact: true }).filter({ visible: true }),
  ).toHaveValue('73')
  await page.getByLabel('random_state', { exact: true }).filter({ visible: true }).fill('91')
  await module(page, '相关网络')
  await expect(page.getByLabel('layer', { exact: true }).filter({ visible: true })).toHaveValue(
    'scmm_input_0',
  )
  await page
    .getByLabel('layer', { exact: true })
    .filter({ visible: true })
    .selectOption({ label: '当前矩阵' })
  let computations = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/analysis/operation')) computations++
  })
  await module(page, '降维')
  await page.getByLabel('random_state', { exact: true }).filter({ visible: true }).fill('12')
  await module(page, '监督与 SHAP')
  await expect(
    page.getByLabel('random_state', { exact: true }).filter({ visible: true }),
  ).toHaveValue('91')
  await page.getByRole('link', { name: /结果与保存/ }).click()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await expect(
    page.getByLabel('random_state', { exact: true }).filter({ visible: true }),
  ).toHaveValue('91')
  expect(computations).toBe(0)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  legacy = false
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '分析设置迁移' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await module(page, '监督与 SHAP')
  await expect(
    page.getByLabel('random_state', { exact: true }).filter({ visible: true }),
  ).toHaveValue('91')
  await expect(page.getByLabel('latent_key', { exact: true })).toHaveValue('X_old_latent')
  await module(page, '相关网络')
  await expect(page.getByLabel('layer', { exact: true }).filter({ visible: true })).toHaveValue(
    '当前矩阵',
  )
  for (const width of [700, 390]) {
    await page.setViewportSize({ width, height: 900 })
    for (const id of ['embedding', 'differential', 'network', 'supervised']) {
      await page.getByRole('combobox', { name: '分析功能', exact: true }).selectOption(id)
      await expect
        .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        .toBe(true)
    }
    await page.screenshot({ path: test.info().outputPath(`analysis-${width}.png`), fullPage: true })
  }
  legacy = false
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await importAnalysis(page, '分析新项目重置')
  await page.getByRole('combobox', { name: '分析功能', exact: true }).selectOption('embedding')
  await expect(page.getByLabel('store_key', { exact: true })).toHaveValue('X_pca')
  await expect(
    page.getByLabel('random_state', { exact: true }).filter({ visible: true }),
  ).toHaveValue('42')
  await page.getByRole('combobox', { name: '分析功能', exact: true }).selectOption('supervised')
  await expect(page.getByLabel('latent_key', { exact: true })).toHaveValue('X_latent')
  await expect(
    page.getByLabel('random_state', { exact: true }).filter({ visible: true }),
  ).toHaveValue('42')
})

test('whole execution chain stays locked, plot retry and calculation failure retain results', async ({
  page,
}) => {
  await importAnalysis(page, '分析执行互斥')
  await module(page, '相关网络')
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const reading = new Promise<void>((resolve) => {
    entered = resolve
  })
  let hold = true,
    failPlot = true,
    failCalculation = false,
    calculations = 0
  await page.route('**/analysis/results/network?*', async (route) => {
    if (hold) {
      entered()
      await held
      hold = false
    }
    await route.continue()
  })
  await page.route('**/analysis/operation', async (route) => {
    calculations++
    if (failCalculation)
      await route.fulfill({ status: 400, json: { error: { message: '合成计算失败' } } })
    else await route.continue()
  })
  await page.route('**/analysis/plot', async (route) => {
    if (failPlot) {
      failPlot = false
      await route.fulfill({ status: 400, json: { error: { message: '合成绘图失败' } } })
    } else await route.continue()
  })
  await page.getByRole('button', { name: '计算相关网络', exact: true }).click()
  await reading
  await expect(page.getByRole('button', { name: '计算相关网络', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '应用视图设置', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '计算相关网络', exact: true }).dispatchEvent('click')
  expect(calculations).toBe(1)
  release()
  await expect(page.getByRole('alert')).toContainText('计算已完成，结果已保留')
  await expect(page.locator('.js-plotly-plot')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '读取相关网络', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '读取相关网络', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  failCalculation = true
  await page.getByRole('button', { name: '计算相关网络', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('合成计算失败')
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByRole('button', { name: '读取相关网络', exact: true })).toBeVisible()
})

for (const staleFailure of [false, true]) {
  test(`late feature ${staleFailure ? 'failure' : 'success'} from a closed project is ignored`, async ({
    page,
  }) => {
    // Slow state reads must finish before the new project's controls accept changes.
    await page.route('**/workspace/analysis', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500))
      await route.continue()
    })
    await importAnalysis(page, '迟到响应旧项目')
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let entered!: () => void
    const requested = new Promise<void>((resolve) => {
      entered = resolve
    })
    await page.route('**/analysis/features?*', async (route) => {
      if (new URL(route.request().url()).searchParams.get('query') === 'delayed') {
        entered()
        await held
        await route.fulfill(
          staleFailure
            ? { status: 400, json: { error: { message: '旧项目迟到错误' } } }
            : { json: { rows: [{ value: 'OLD', label: '旧项目迟到特征' }], total: 1 } },
        )
      } else await route.continue()
    })
    await page.getByLabel('Color source', { exact: true }).selectOption('feature')
    await page.getByLabel('Search', { exact: true }).fill('delayed')
    await requested
    await page.getByRole('button', { name: '关闭项目', exact: true }).click()
    await importAnalysis(page, '迟到响应新项目')
    const late = page.waitForResponse((response) => response.url().includes('query=delayed'))
    release()
    await late
    await page.getByLabel('Color source', { exact: true }).selectOption('feature')
    await expect(
      page.getByLabel('Color', { exact: true }).locator('option[value="f0"]'),
    ).toHaveCount(0)
    await expect(
      page.getByLabel('Color', { exact: true }).locator('option[value="feature:f0"]'),
    ).toHaveCount(1)
    await expect(page.getByText('旧项目迟到特征', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('alert')).toHaveCount(0)
  })
}

test('PCA axes, stable cell clicks, paper exports and complete heatmap data', async ({ page }) => {
  test.setTimeout(90000)
  await importAnalysis(page, '论文图与细胞联动')
  await page.getByLabel('n_components', { exact: true }).fill('4')
  await page.getByRole('button', { name: '运行降维', exact: true }).click()
  await expect(page.getByLabel('查看嵌入', { exact: true })).toHaveValue('X_pca')
  await page
    .getByRole('combobox', { name: '显示维度', exact: true })
    .selectOption({ label: '三维' })
  const projected = page.waitForResponse(
    (r) =>
      r.url().endsWith('/analysis/plot') &&
      JSON.stringify(r.request().postDataJSON().options.dimensions) === '[1,2,4]',
  )
  await page.getByLabel('Z 轴', { exact: true }).fill('4')
  expect((await projected).ok()).toBe(true)
  await expect(page.getByRole('cell', { name: 'PC4', exact: true })).toBeVisible()
  await page
    .locator('.js-plotly-plot')
    .first()
    .evaluate((el) => {
      const plot = el as HTMLElement & { emit: (name: string, event: unknown) => void }
      plot.emit('plotly_click', { points: [{ customdata: ['c0'] }] })
      plot.emit('plotly_click', { points: [{ customdata: ['c33'] }] })
    })
  await expect(page.getByRole('heading', { name: '所选细胞质谱' })).toBeVisible()
  await page.getByRole('button', { name: '查看质谱', exact: true }).click()
  const spectra = page
    .locator('.plot-shell')
    .filter({ has: page.getByLabel('图文件名：cell-spectra', { exact: true }) })
  await expect(spectra.locator('.js-plotly-plot')).toBeVisible()
  const pdf = page.waitForEvent('download')
  await spectra.getByRole('button', { name: '下载 PDF', exact: true }).click()
  expect((await pdf).suggestedFilename()).toBe('cell-spectra.pdf')
  await module(page, '热图')
  await page.getByLabel('特征编号（换行或逗号分隔）', { exact: true }).fill('f0\nf1\nf2')
  await page.getByRole('combobox', { name: '列汇总', exact: true }).selectOption('group')
  await page.getByRole('combobox', { name: '均值的样本权重列', exact: true }).selectOption('sample')
  await page
    .getByRole('combobox', { name: '均值权重', exact: true })
    .selectOption({ label: '样本等权' })
  await page.getByRole('button', { name: '生成热图', exact: true }).click()
  const heatmap = page
    .locator('.plot-shell')
    .filter({ has: page.getByLabel('图文件名：heatmap', { exact: true }) })
  await expect(heatmap.locator('.js-plotly-plot')).toBeVisible()
  const download = page.waitForEvent('download')
  await heatmap.getByRole('button', { name: '下载作图数据', exact: true }).click()
  expect((await download).suggestedFilename()).toBe('heatmap-data.zip')
  await module(page, '差异与 Marker')
  await page.getByRole('button', { name: '计算分类权重 Marker', exact: true }).click()
  await expect(page.getByRole('columnheader', { name: /符号稳定性/ })).toBeVisible()
})

for (const editTiming of ['before-response', 'after-response', 'no-edit'] as const) {
  test(`maintenance draft cannot overwrite a newer edit ${editTiming}`, async ({ page }) => {
    await importAnalysis(page, `草稿恢复输入保护 ${editTiming}`)
    const workspace = await page.evaluate(() => sessionStorage.getItem('scmm-workspace')!)
    const state = await (
      await page.request.get('/api/v1/workspace', {
        headers: { 'X-SCMM-Workspace': workspace },
      })
    ).json()
    let release!: () => void
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    let received = false
    await page.route('**/workspace/maintenance/draft', async (route) => {
      if (route.request().method() !== 'GET') return route.continue()
      received = true
      await gate
      await route.fulfill({
        json: {
          project_path: state.project.path,
          route: '/analysis',
          forms: { '/analysis': [{ key: 'random_state#0', value: '17', checked: false }] },
        },
      })
    })
    await page.reload()
    await expect.poll(() => received).toBe(true)
    const seed = page.getByLabel('random_state', { exact: true }).filter({ visible: true })
    await expect(seed).toBeVisible()
    const response = page.waitForResponse(
      (value) =>
        value.url().endsWith('/workspace/maintenance/draft') && value.request().method() === 'GET',
    )
    if (editTiming === 'before-response') await seed.fill('91')
    release()
    await response
    if (editTiming === 'after-response') await seed.fill('91')
    // The deferred DOM restoration is scheduled for 500 ms after hydration.
    await page.waitForTimeout(750)
    await expect(seed).toHaveValue(editTiming === 'no-edit' ? '17' : '91')
  })
}

test('draft capture drops forms from the preceding project', async ({ page }) => {
  const drafts: { project_path: string; forms: Record<string, unknown> }[] = []
  page.on('request', (request) => {
    if (request.url().endsWith('/workspace/draft') && request.method() === 'PUT')
      drafts.push(request.postDataJSON().state)
  })
  await importAnalysis(page, '前一个项目草稿')
  await page.getByLabel('store_key', { exact: true }).fill('X_only_previous_project')
  await expect.poll(() => drafts.some((value) => Boolean(value.forms['/analysis']))).toBe(true)
  const previous = drafts.at(-1)!.project_path
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page.getByLabel('项目名称', { exact: true }).fill('后一个项目草稿')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await expect
    .poll(() =>
      drafts.some((value) => Boolean(value.project_path) && value.project_path !== previous),
    )
    .toBe(true)
  const current = drafts.find(
    (value) => Boolean(value.project_path) && value.project_path !== previous,
  )!
  expect(current.forms['/analysis']).toBeUndefined()
  expect(JSON.stringify(current)).not.toContain('X_only_previous_project')
})

test('clustering parameters execute explicitly and persist across saved project reopen', async ({
  page,
}) => {
  await importAnalysis(page, '聚类高级参数')
  await module(page, '聚类')
  await page.getByLabel('clustering', { exact: true }).selectOption('dbscan')
  await expect(page.getByLabel('eps', { exact: true })).toHaveValue('0.5')
  await expect(page.getByLabel('min_samples', { exact: true })).toHaveValue('5')
  await page.getByLabel('eps', { exact: true }).fill('0.001')
  await page.getByLabel('min_samples', { exact: true }).fill('2')
  await page
    .locator('summary')
    .filter({ hasText: /^聚类高级参数$/ })
    .click()
  await page.getByLabel('聚类距离', { exact: true }).selectOption('manhattan')
  await page.getByLabel('cluster_key', { exact: true }).fill('db_custom')
  const ran = page.waitForResponse(
    (response) =>
      response.url().endsWith('/analysis/operation') &&
      response.request().postDataJSON()?.operation === 'cluster',
  )
  await page.getByRole('button', { name: '运行聚类', exact: true }).click()
  const response = await ran
  expect(response.status()).toBe(200)
  expect(response.request().postDataJSON().options).toMatchObject({
    eps: 0.001,
    min_samples: 2,
    metric: 'manhattan',
  })
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '聚类高级参数' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await module(page, '聚类')
  await expect(page.getByLabel('eps', { exact: true })).toHaveValue('0.001')
  await expect(page.getByLabel('min_samples', { exact: true })).toHaveValue('2')
  await page.getByLabel('clustering', { exact: true }).selectOption('louvain')
  await expect(page.getByLabel('聚类分辨率', { exact: true })).toHaveValue('1')
  await page.getByLabel('聚类分辨率', { exact: true }).fill('0.7')
  await page.getByLabel('cluster_key', { exact: true }).fill('louvain_custom')
  const graph = page.waitForResponse(
    (value) =>
      value.url().endsWith('/analysis/operation') &&
      value.request().postDataJSON()?.operation === 'cluster',
  )
  await page.getByRole('button', { name: '运行聚类', exact: true }).click()
  const graphResult = await graph
  expect(graphResult.status()).toBe(200)
  expect(graphResult.request().postDataJSON().options.resolution).toBe(0.7)
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('exact feature scatter plots manually and reloads a saved exportable figure', async ({
  page,
}) => {
  await importAnalysis(page, '双特征散点闭环')
  await module(page, '双特征散点')
  const x = page.getByLabel('散点横轴特征', { exact: true })
  const y = page.getByLabel('散点纵轴特征', { exact: true })
  await expect(x.locator('option[value="f0"]')).toBeAttached()
  await x.selectOption('f0')
  await y.selectOption('f1')
  await page.getByLabel('散点着色列', { exact: true }).selectOption('group')
  await expect(page.locator('.js-plotly-plot')).toHaveCount(0)
  await page.getByRole('button', { name: '绘制双特征散点', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByLabel('散点回归摘要')).toContainText('有限细胞数：64')
  await page.getByLabel('散点特征搜索', { exact: true }).fill('f3')
  await expect(x).toHaveValue('f0')
  await expect(y).toHaveValue('f1')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载作图数据', exact: true }).click()
  expect((await download).suggestedFilename()).toMatch(/\.zip$/)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '双特征散点闭环' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await module(page, '双特征散点')
  await expect(x).toHaveValue('f0')
  await expect(y).toHaveValue('f1')
  await page.getByRole('button', { name: '读取已保存散点', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByRole('button', { name: '下载作图数据', exact: true })).toBeEnabled()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('feature-distance embedding exports distances and reloads a read-only figure', async ({
  page,
}) => {
  test.setTimeout(120000)
  await importAnalysis(page, '特征距离嵌入')
  await module(page, '特征距离嵌入')
  await page.getByLabel('距离嵌入特征ID', { exact: true }).fill('f0,f1,f2,f3')
  await page.getByLabel('特征嵌入距离', { exact: true }).selectOption('euclidean')
  await page.getByRole('button', { name: '生成特征距离嵌入', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('button', { name: '下载作图数据', exact: true })).toBeEnabled()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载作图数据', exact: true }).click()
  expect((await download).suggestedFilename()).toMatch(/\.zip$/)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '特征距离嵌入' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await module(page, '特征距离嵌入')
  await expect(page.getByLabel('距离嵌入特征ID', { exact: true })).toHaveValue('f0\nf1\nf2\nf3')
  await page.getByRole('button', { name: '读取已保存特征距离嵌入', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('acquisition stability requires explicit choices and persists full tables', async ({
  page,
}) => {
  await importAnalysis(page, '采集稳定性')
  await module(page, '采集稳定性 QC')
  const generate = page.getByRole('button', { name: '生成采集稳定性 QC', exact: true })
  await expect(generate).toBeDisabled()
  await page.getByLabel('稳定性参考特征', { exact: true }).selectOption('f0')
  await page.getByLabel('稳定性来源列', { exact: true }).selectOption('sample')
  await page.getByLabel('稳定性坐标含义', { exact: true }).selectOption('stored_order')
  await page.getByLabel('稳定性窗口数', { exact: true }).fill('4')
  await generate.click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByText(/坐标含义：当前存储顺序/)).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载作图数据', exact: true }).click()
  expect((await download).suggestedFilename()).toMatch(/\.zip$/)
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '采集稳定性' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await module(page, '采集稳定性 QC')
  await expect(page.getByLabel('稳定性坐标含义', { exact: true })).toHaveValue('stored_order')
  await page.getByRole('button', { name: '读取已保存采集稳定性 QC', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('explicit model parameters reach training and persist display settings', async ({ page }) => {
  await importAnalysis(page, '模型高级参数')
  await module(page, '监督与 SHAP')
  await page.getByLabel('label_key', { exact: true }).selectOption('group')
  await page.getByLabel('验证方式', { exact: true }).selectOption('cell')
  await page.getByText('监督高级参数', { exact: true }).click()
  await page.getByLabel('logistic C', { exact: true }).fill('0.25')
  await page.getByLabel('cv', { exact: true }).fill('2')
  const request = page.waitForRequest(
    (r) => r.url().endsWith('/analysis/operation') && r.postDataJSON()?.operation === 'train',
  )
  await page.getByRole('button', { name: '训练并验证', exact: true }).click()
  expect((await request).postDataJSON().options.model_params.C).toBe(0.25)
  await expect(page.getByRole('button', { name: '读取监督诊断', exact: true })).toBeVisible()
  await page.getByLabel('SHAP 显示特征数', { exact: true }).fill('7')
  await page.getByLabel('model', { exact: true }).selectOption('random_forest')
  await page.getByLabel('random_forest n_estimators', { exact: true }).fill('7')
  await page.getByLabel('random_forest min_samples_leaf', { exact: true }).fill('0.1')
  await page.getByRole('link', { name: /结果与保存/ }).click()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await expect(page.getByLabel('random_forest n_estimators', { exact: true })).toHaveValue('7')
  await expect(page.getByLabel('SHAP 显示特征数', { exact: true })).toHaveValue('7')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '模型高级参数' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await module(page, '监督与 SHAP')
  await page.getByText('监督高级参数', { exact: true }).click()
  await expect(page.getByLabel('random_forest min_samples_leaf', { exact: true })).toHaveValue(
    '0.1',
  )
  await expect(page.getByLabel('SHAP 显示特征数', { exact: true })).toHaveValue('7')
})

test('image exports show backend stale-source rejection without a download', async ({ page }) => {
  await importAnalysis(page, '图像来源失效')
  await page.getByRole('button', { name: '运行降维', exact: true }).click()
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  let downloads = 0
  page.on('download', () => downloads++)
  await page.route('**/workspace/figures/check', async (route) => {
    expect(route.request().postDataJSON().metadata.dataset_token).toHaveLength(2)
    await route.fulfill({
      status: 400,
      json: { error: { message: '图形已过期，请基于当前数据重新绘图。' } },
    })
  })
  await page.getByRole('button', { name: '下载 SVG', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('图形已过期，请基于当前数据重新绘图。')
  expect(downloads).toBe(0)
})

test('named Palantir and window results retain exact sources through save and reload', async ({
  page,
}) => {
  test.setTimeout(90000)
  await importAnalysis(page, '命名时间结果', 'time.h5ad')
  await page.getByLabel('n_components', { exact: true }).fill('3')
  await page.getByRole('button', { name: '运行降维', exact: true }).click()
  await expect(page.getByLabel('查看嵌入', { exact: true })).toHaveValue('X_pca')
  await module(page, '伪时间与轨迹')
  let calculations = 0
  page.on('request', (request) => {
    if (request.url().endsWith('/analysis/time') && request.method() === 'POST') calculations++
  })
  await expect(page.getByRole('button', { name: '计算并应用时间结果', exact: true })).toBeDisabled()
  await page.getByLabel('时间结果输出键', { exact: true }).fill('pal_browser')
  await page.getByLabel('根点细胞 ID', { exact: true }).fill('c3')
  await page.getByLabel('Palantir 输入表示', { exact: true }).selectOption('X')
  await page.getByLabel('终末细胞 ID', { exact: true }).fill('c39')
  await page.getByLabel('扩散成分数', { exact: true }).fill('3')
  await page.getByLabel('Palantir 近邻数', { exact: true }).fill('10')
  await page.getByLabel('路标数量', { exact: true }).fill('12')
  await page.getByRole('button', { name: '计算并应用时间结果', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '结果 pal_browser 的生效参数', exact: true }),
  ).toBeVisible()
  await page.getByLabel('时间图绘图坐标', { exact: true }).selectOption('X_pca')
  await page.getByRole('button', { name: '绘制时间结果', exact: true }).click()
  await expect(page.getByText('图来源结果：pal_browser', { exact: true })).toBeVisible()
  await page.getByLabel('时间分析方法', { exact: true }).selectOption('trajectory')
  await page.getByLabel('时间结果输出键', { exact: true }).fill('path_browser')
  await page.getByLabel('轨迹坐标', { exact: true }).selectOption('X_pca')
  await page.getByLabel('轨迹时间列', { exact: true }).selectOption('pal_browser_pseudotime')
  await page.getByLabel('轨迹时间含义', { exact: true }).selectOption('pseudotime')
  await expect(page.getByLabel('轨迹时间单位', { exact: true })).toHaveValue('unitless')
  await page.getByLabel('轨迹分支概率', { exact: true }).selectOption('pal_browser_branch_probs')
  await page.getByLabel('时间窗口细胞数', { exact: true }).fill('16')
  await page.getByLabel('窗口步长细胞数', { exact: true }).fill('8')
  await page.getByRole('button', { name: '计算并应用时间结果', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '结果 path_browser 的生效参数', exact: true }),
  ).toBeVisible()
  await page.getByRole('button', { name: '绘制时间结果', exact: true }).click()
  await expect(page.getByText('图来源结果：path_browser', { exact: true })).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载完整时间结果 ZIP', exact: true }).click()
  expect((await download).suggestedFilename()).toBe('scmm-time-result.zip')
  expect(calculations).toBe(2)
  for (const width of [700, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
      .toBe(true)
  }
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.locator('.save-state').filter({ hasText: /^已保存$/ })).toBeVisible()
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '命名时间结果' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page.getByRole('heading', { name: '预处理与 QC', exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^5\s*分析$/ }).click()
  await page.getByRole('combobox', { name: '分析功能', exact: true }).selectOption('time')
  await expect(page.getByLabel('选择命名时间结果', { exact: true })).toHaveValue('path_browser')
  await page.getByRole('button', { name: '读取已保存时间图', exact: true }).click()
  await expect(page.getByText('图来源结果：path_browser', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '读取时间结果表', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: '结果 path_browser 的生效参数', exact: true }),
  ).toBeVisible()
  expect(calculations).toBe(2)
})
