import { test, expect, navigate, type Page } from './fixtures'
import { createProject } from './support/project'

test.use({ viewport: { width: 1920, height: 1080 } })

function peak(page: Page, id: string) {
  return page
    .getByRole('complementary', { name: '峰列表' })
    .locator('button')
    .filter({
      has: page.getByText(id, { exact: true }),
    })
}

test('raw overlap and acquisition MS2 stay traceable through the desktop review layout', async ({
  page,
}) => {
  test.setTimeout(90000)
  await createProject(page, '原始谱证据复核')
  await navigate(page, '/annotation')
  const exchange = page.getByRole('region', { name: '板块数据导入与导出' })
  await exchange.getByRole('button', { name: '导入外部数据' }).click()
  await exchange.getByLabel('板块导入格式').selectOption('feature_csv')
  await exchange.getByLabel('板块数据文件').setInputFiles({
    name: 'profile-features.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('feature_id,mz\nparent,758.569434493991\ncompeting,760.585084557791\n'),
  })
  await exchange.getByRole('button', { name: '检查并导入本板块' }).click()
  await navigate(page, '/samples')
  await page.getByRole('button', { name: '＋ 添加原始文件' }).click()
  await page.getByRole('button', { name: /annotation-profile.mzML/ }).click()
  await page.getByRole('button', { name: '添加 1 个文件', exact: true }).click()
  await navigate(page, '/annotation')
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  await spectrum.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByLabel('脂质数据库文件').selectOption({ label: 'zz-profile.sdf' })
  await page.getByRole('button', { name: '运行精确质量候选注释' }).click()
  await peak(page, 'parent').click()
  await spectrum.getByRole('button', { name: '选入原始谱复核' }).click()
  await peak(page, 'competing').click()
  await spectrum.getByRole('button', { name: '选入原始谱复核' }).click()
  await expect(spectrum.locator('.js-plotly-plot')).toBeInViewport({ ratio: 0.9 })
  await spectrum.getByRole('button', { name: '原始谱复核 · 2/2' }).click()
  const dialog = page.getByRole('dialog', { name: '原始谱重叠复核' })
  await dialog.getByLabel('项目样本').selectOption({ label: 'annotation-profile' })
  await dialog.getByLabel('MS1 扫描索引').fill('0')
  await dialog.getByRole('button', { name: '运行并记录复核' }).click()
  await expect(dialog).toContainText('scan=47')
  await expect(dialog).toContainText('8.94 mDa')
  await expect(dialog.locator('.js-plotly-plot')).toBeInViewport({ ratio: 0.95 })
  await dialog.getByRole('link', { name: /打开证据记录/ }).click()
  await expect(page.getByRole('region', { name: '原始谱复核结果' })).toContainText('scan=47')

  await page.getByRole('button', { name: 'MS/MS 搜索', exact: true }).click()
  await page.getByLabel('实测来源').selectOption('acquisition')
  await page.getByLabel('项目采集文件').selectOption({ label: 'annotation-profile' })
  await page.getByLabel('起始扫描索引').fill('1')
  await page.getByLabel('结束扫描索引').fill('1')
  await page.getByLabel('参考谱库').setInputFiles({
    name: 'reference.mgf',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'BEGIN IONS\nTITLE=reference\nPEPMASS=758.569434493991\n120 20\n140 60\n160 10\nEND IONS\n',
    ),
  })
  await page.getByLabel('样本池与适用范围').fill('Synthetic pool')
  const search = page.getByRole('button', { name: '搜索候选证据' })
  await expect(search).toBeInViewport()
  await search.click()
  await page.getByLabel('显示全部峰的比对').check()
  const row = page.getByRole('button', { name: /parent \/ scan=48/ })
  await expect(row).toBeVisible()
  await row.click()
  await expect(page.getByText(/隔离窗偏移 0.4 \/ 0.6 Da/)).toBeVisible()
  await expect(page.getByText(/采集碰撞能 25/)).toBeVisible()
  await navigate(page, '/ions')
  await expect(page.getByRole('heading', { name: '定量视图', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('complete feature spectrum is selectable before candidate search, including identical masses', async ({
  page,
}) => {
  await createProject(page, '查库前全谱与重叠峰')
  await navigate(page, '/annotation')
  const exchange = page.getByRole('region', { name: '板块数据导入与导出' })
  await exchange.getByRole('button', { name: '导入外部数据' }).click()
  await exchange.getByLabel('板块导入格式').selectOption('feature_csv')
  await exchange.getByLabel('板块数据文件').setInputFiles({
    name: 'features.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'feature_id,mz\nfirst,123.456789\nsecond,123.456789\ncandidate,316.320225793\n',
    ),
  })
  await exchange.getByRole('button', { name: '检查并导入本板块' }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  const plot = spectrum.locator('.js-plotly-plot')
  await spectrum.getByRole('button', { name: '查看完整谱图', exact: true }).click()
  await expect(plot).toContainText('Full feature spectrum')
  await expect(plot).toBeInViewport({ ratio: 0.95 })
  const markers = plot.locator('.scatterlayer .trace .points path.point')
  await expect(markers).toHaveCount(3)
  await markers.first().click({ force: true })
  await expect(spectrum.getByText('此位置有 2 个可选峰')).toBeVisible()
  await spectrum.getByRole('button', { name: /^second · m\/z/ }).click()
  await expect(spectrum.locator('.selected-peak')).toContainText('选中 second')
  await spectrum.getByLabel('定位峰').fill('first')
  await expect(spectrum.getByText('当前峰在列表筛选范围之外。')).toBeVisible()
  await spectrum.getByRole('button', { name: '恢复全谱', exact: true }).click()
  await expect(spectrum.locator('.selected-peak')).toContainText('选中 second')
  await spectrum.getByRole('button', { name: '返回局部谱图', exact: true }).click()
  await expect(plot).toContainText('Local feature spectrum')
  await expect(spectrum.locator('.selected-peak')).toContainText('选中 second')
  await spectrum.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByLabel('脂质数据库文件').selectOption('preset:mammalian_cells')
  await page.getByRole('button', { name: '运行精确质量候选注释', exact: true }).click()
  await expect(spectrum.locator('.selected-peak')).toContainText('已查未命中')
  await expect(spectrum.getByLabel('峰标签内容')).toHaveValue('both')
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('standalone feature annotation uses mammalian preset and persists reviewed MS2 labels', async ({
  page,
}) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await createProject(page, '独立注释与二级状态')
  await navigate(page, '/annotation')
  const exchange = page.getByRole('region', { name: '板块数据导入与导出' })
  await exchange.getByRole('button', { name: '导入外部数据' }).click()
  await exchange.getByLabel('板块导入格式').selectOption('feature_csv')
  await exchange.getByLabel('板块数据文件').setInputFiles({
    name: 'features.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('feature_id,mz\nmc,316.320225793\nunknown,123.456789\n'),
  })
  await exchange.getByRole('button', { name: '检查并导入本板块' }).click()
  await expect(page.getByLabel('谱图来源')).toContainText('独立特征表')
  await page.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByLabel('脂质数据库文件').selectOption('preset:mammalian_cells')
  await page.getByRole('button', { name: '运行精确质量候选注释', exact: true }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  await expect(spectrum.locator('.js-plotly-plot')).toBeVisible()
  await expect(spectrum).toContainText('没有实测强度')
  await expect(spectrum.getByLabel('谱图强度显示')).toBeDisabled()
  await peak(page, 'mc').click()
  await expect(spectrum.locator('.selected-peak')).toContainText('SPB19:0;O2')
  await expect(spectrum.locator('.selected-peak')).toContainText('MS2: Not supplied')
  await page.getByLabel('人工注释名称', { exact: true }).fill('人工名称保留原文')
  await page.getByRole('button', { name: '保存人工指定', exact: true }).click()
  await expect(spectrum.locator('.selected-peak')).toContainText('人工名称保留原文')
  const download = page.waitForEvent('download')
  await exchange.getByRole('button', { name: '导出本板块数据' }).click()
  expect((await download).suggestedFilename()).toMatch(/scmm-exchange\.zip$/)
  await page.getByRole('button', { name: '保存项目', exact: true }).first().click()
  await page.reload()
  await expect(page.getByLabel('脂质查看版本')).not.toHaveValue('')
  await peak(page, 'mc').click()
  await expect(page.getByLabel('人工注释名称', { exact: true })).toHaveValue('人工名称保留原文')
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '独立注释与二级状态' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page).toHaveURL(/\/annotation$/)
  await peak(page, 'mc').click()
  await expect(page.getByLabel('人工注释名称', { exact: true })).toHaveValue('人工名称保留原文')
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('algae database shows original evidence and inconsistent formula in candidate review', async ({
  page,
}) => {
  await createProject(page, '藻类数据库注释')
  await navigate(page, '/annotation')
  const exchange = page.getByRole('region', { name: '板块数据导入与导出' })
  await exchange.getByRole('button', { name: '导入外部数据' }).click()
  await exchange.getByLabel('板块导入格式').selectOption('feature_csv')
  await exchange.getByLabel('板块数据文件').setInputFiles({
    name: 'algae-features.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('feature_id,mz\nsource_ms2,451.319438\nconflict,734.5929\n'),
  })
  await exchange.getByRole('button', { name: '检查并导入本板块' }).click()
  await page.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByLabel('脂质数据库文件').selectOption({ label: '藻类数据库 · 251 条候选' })
  await page.getByRole('button', { name: '运行精确质量候选注释', exact: true }).click()

  await peak(page, 'source_ms2').click()
  const cards = page.locator('.candidate-card').filter({ visible: true })
  const sourceCandidate = cards.filter({ hasText: 'ST 28:3;O3' })
  await expect(sourceCandidate).toContainText('原表注释 MS2 matched · MSI Level 2')
  await expect(sourceCandidate).toContainText('MS2: Not supplied')
  await sourceCandidate.getByText('候选详情', { exact: true }).click()
  await expect(sourceCandidate).toContainText('451.319438')

  await peak(page, 'conflict').click()
  const conflict = cards.filter({ hasText: 'DGTS 34:3' })
  await expect(conflict).toContainText('原表理论 m/z 与分子式及加合物不一致')
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('clicking an observed peak links the candidate table and spectrum review controls', async ({
  page,
}) => {
  test.setTimeout(90000)
  await createProject(page, '谱图点击与关联审核')
  await page.getByRole('button', { name: '导入 H5AD 数据', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ lipids.h5ad/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await navigate(page, '/annotation')
  await page.getByRole('button', { name: '查看完整谱图', exact: true }).click()
  await page.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByRole('button', { name: '运行注释与同位素标记', exact: true }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  const chart = spectrum.locator('.js-plotly-plot')
  await expect(chart).toContainText('Full feature spectrum')
  await chart.evaluate((element) => element.setAttribute('data-review-plot', 'mounted'))
  await chart.locator('.scatterlayer .trace .points path.point').first().click({ force: true })
  await expect(peak(page, 'f_h')).toHaveAttribute('aria-pressed', 'true')
  await expect(spectrum.locator('.selected-peak')).toContainText('f_h')
  await spectrum.getByRole('button', { name: '峰关系', exact: true }).click()
  await expect(
    spectrum.getByRole('button', { name: '接受关联', exact: true }).first(),
  ).toBeVisible()
  await spectrum.getByRole('button', { name: '接受关联', exact: true }).first().click()
  await expect(spectrum.getByText(/同位素 · 已确认|加合离子 · 已确认/).first()).toBeVisible()
  await expect(chart).toHaveAttribute('data-review-plot', 'mounted')
  await spectrum.getByRole('button', { name: '候选', exact: true }).click()
  await page.getByLabel('人工注释名称', { exact: true }).fill('Reviewed candidate')
  await page.getByRole('button', { name: '保存人工指定', exact: true }).click()
  await expect(spectrum.locator('.selected-peak')).toContainText('Reviewed candidate')
  await spectrum.getByLabel('谱图强度显示').selectOption('true')
  await expect(chart).toContainText('Relative abundance (%)')
  await spectrum.getByRole('button', { name: '恢复全谱', exact: true }).click()
  await spectrum.screenshot({ path: test.info().outputPath('annotation-spectrum.png') })
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
    .toBe(true)
  await expect(
    chart.locator('.annotation-text').filter({ hasText: 'Reviewed candidate' }).first(),
  ).toBeVisible()
  await expect
    .poll(() =>
      chart.evaluate((element) => {
        const boxes = [...element.querySelectorAll('.annotation-text')]
          .map((label) => ({ box: label.getBoundingClientRect(), text: label.textContent }))
          .filter(({ box }) => box.width && box.height)
        const overlaps: string[] = []
        for (let left = 0; left < boxes.length; left++) {
          for (let right = left + 1; right < boxes.length; right++) {
            const a = boxes[left]!.box,
              b = boxes[right]!.box
            if (
              a.left < b.right - 1 &&
              a.right > b.left + 1 &&
              a.top < b.bottom - 1 &&
              a.bottom > b.top + 1
            )
              overlaps.push(`${boxes[left]!.text} / ${boxes[right]!.text}`)
          }
        }
        return overlaps
      }),
    )
    .toEqual([])
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('an imported matrix with unknown intensity provenance can run mass-only annotation', async ({
  page,
}) => {
  await createProject(page, '外部矩阵质量候选')
  await navigate(page, '/annotation')
  const exchange = page.getByRole('region', { name: '板块数据导入与导出' })
  await exchange.getByRole('button', { name: '导入外部数据' }).click()
  await exchange.getByLabel('板块导入格式').selectOption('matrix_csv')
  await exchange.getByLabel('观测单位').selectOption('sample')
  await exchange.getByLabel('板块数据文件').setInputFiles({
    name: 'matrix.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('Sample,Label,316.320225793\ns1,A,10\ns2,B,11\n'),
  })
  await exchange.getByRole('button', { name: '检查并导入本板块' }).click()
  await page.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByLabel('脂质数据库文件').selectOption('preset:mammalian_cells')
  await expect(page.getByLabel('注释证据模式')).toHaveValue('true')
  await page.getByRole('button', { name: '运行精确质量候选注释', exact: true }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  await expect(spectrum.locator('.js-plotly-plot')).toBeVisible()
  await expect(spectrum.locator('.js-plotly-plot')).toContainText('Mean matrix value')
  await expect(spectrum.getByLabel('谱图强度显示')).toBeDisabled()
  await peak(page, '316.320225793').click()
  await expect(spectrum.locator('.selected-peak')).toContainText('SPB19:0;O2')
  await expect(page.getByRole('alert')).toHaveCount(0)
})
