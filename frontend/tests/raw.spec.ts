import { test, expect, type Page } from './fixtures'
import { createProject as create } from './support/project'

test.use({ actionTimeout: 15000 })

async function noError(page: Page) {
  await expect(page.getByRole('alert')).toHaveCount(0)
}

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

test('raw zoom, reset then zoom, and full-range SVG share one explicit export policy', async ({
  page,
}) => {
  const { readFile } = await import('node:fs/promises')
  await create(page, '原始谱统一视图导出')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
  const plot = page.locator('.plot-shell').first()
  await expect(plot.locator('.js-plotly-plot')).toBeVisible()
  await expect(plot.getByLabel('导出范围', { exact: true })).toHaveValue('current')
  const drag = plot.locator('.nsewdrag').first()
  const box = (await drag.boundingBox())!
  await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.1)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.9, { steps: 10 })
  await page.mouse.up()
  await expect
    .poll(() =>
      plot
        .locator('.js-plotly-plot')
        .evaluate(
          (el) =>
            (el as HTMLElement & { layout: { xaxis: { autorange: boolean } } }).layout.xaxis
              .autorange,
        ),
    )
    .toBe(false)
  async function svgTicks() {
    const pending = page.waitForEvent('download')
    await plot.getByRole('button', { name: '下载 SVG', exact: true }).click()
    const svg = await readFile((await (await pending).path())!, 'utf8')
    expect(svg).toContain('Intensity')
    expect(svg).not.toContain('总离子流')
    return page.evaluate(
      (content) =>
        Array.from(
          new DOMParser().parseFromString(content, 'image/svg+xml').querySelectorAll('.xtick text'),
        ).map((el) => Number(el.textContent)),
      svg,
    )
  }
  const zoomed = await svgTicks()
  expect(Math.min(...zoomed)).toBeGreaterThan(0)
  expect(Math.max(...zoomed)).toBeLessThan(30)
  await plot.locator('.js-plotly-plot').evaluate((el) => {
    const graph = el as HTMLElement & {
      layout: { xaxis: { autorange: boolean; range: number[] } }
      emit: (name: string, value: unknown) => void
    }
    graph.layout.xaxis.autorange = true
    graph.layout.xaxis.range = [0, 30]
    graph.emit('plotly_relayout', { 'xaxis.autorange': true })
    graph.layout.xaxis.autorange = false
    graph.layout.xaxis.range = [11, 15]
    graph.emit('plotly_relayout', { 'xaxis.range[0]': 11, 'xaxis.range[1]': 15 })
  })
  const again = await svgTicks()
  expect(Math.min(...again)).toBeGreaterThanOrEqual(11)
  expect(Math.max(...again)).toBeLessThanOrEqual(15)
  await plot.getByLabel('导出范围', { exact: true }).selectOption('full')
  const full = await svgTicks()
  expect(Math.min(...full)).toBeLessThanOrEqual(0)
  expect(Math.max(...full)).toBeGreaterThanOrEqual(30)
  await noError(page)
})

test('legacy automatic labels become English while input legend and custom title remain unchanged', async ({
  page,
}) => {
  const { readFile } = await import('node:fs/promises')
  await create(page, '历史图英文兼容')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /extract.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await page.route('**/workspace/raw/plot', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    delete body.figure.layout.meta.system_text_language
    body.figure.layout.title.text = '总离子流 TIC'
    body.figure.layout.yaxis.title.text = '强度'
    body.figure.layout.xaxis.title.text = 'RT（秒）'
    body.figure.data[0].name = '用户输入图例'
    await route.fulfill({ response, json: body })
  })
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await page.getByRole('button', { name: '打开原始文件', exact: true }).click()
  const plot = page.locator('.plot-shell').first()
  await expect(plot.locator('.gtitle')).toHaveText('Total ion chromatogram (TIC)')
  await expect(plot.locator('.legendtext')).toHaveText('用户输入图例')
  await plot.locator('.plot-settings > summary').click()
  await plot.getByLabel('导出标题', { exact: true }).fill('强度')
  const download = page.waitForEvent('download')
  await plot.getByRole('button', { name: '下载 SVG', exact: true }).click()
  const svg = await readFile((await (await download).path())!, 'utf8')
  const text = await page.evaluate((content) => {
    const doc = new DOMParser().parseFromString(content, 'image/svg+xml')
    return {
      title: doc.querySelector('.gtitle')?.textContent,
      axis: doc.querySelector('.ytitle')?.textContent,
      legend: doc.querySelector('.legendtext')?.textContent,
    }
  }, svg)
  expect(text).toEqual({ title: '强度', axis: 'Intensity', legend: '用户输入图例' })
  await noError(page)
})
