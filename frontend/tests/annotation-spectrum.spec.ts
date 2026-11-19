import { test, expect, navigate } from './fixtures'
import { createProject } from './support/project'

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
  await expect(exchange).toContainText('独立特征表')
  await page.getByLabel('脂质数据库文件').selectOption('preset:mammalian_cells')
  await page.getByRole('button', { name: '运行精确质量候选注释', exact: true }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  await expect(spectrum.locator('.js-plotly-plot')).toBeVisible()
  await expect(spectrum).toContainText('没有实测强度')
  await expect(spectrum.getByLabel('谱图强度显示')).toBeDisabled()
  await page.getByLabel('脂质逐特征核对', { exact: true }).selectOption('mc')
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
  await page.getByLabel('脂质逐特征核对', { exact: true }).selectOption('mc')
  await expect(page.getByLabel('人工注释名称', { exact: true })).toHaveValue('人工名称保留原文')
  await page.getByRole('button', { name: '关闭项目', exact: true }).click()
  await page.getByRole('link', { name: 'scMM 项目首页', exact: true }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '独立注释与二级状态' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page).toHaveURL(/\/annotation$/)
  await page.getByLabel('脂质逐特征核对', { exact: true }).selectOption('mc')
  await expect(page.getByLabel('人工注释名称', { exact: true })).toHaveValue('人工名称保留原文')
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(errors).toEqual([])
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
  await page.getByRole('button', { name: '运行注释与同位素标记', exact: true }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  const chart = spectrum.locator('.js-plotly-plot')
  await expect(chart).toBeVisible()
  await chart.locator('.scatterlayer .trace .points path.point').first().click({ force: true })
  await expect(page.getByLabel('脂质逐特征核对', { exact: true })).toHaveValue('f_h')
  await expect(spectrum.locator('.selected-peak')).toContainText('f_h')
  await expect(
    spectrum.getByRole('button', { name: '接受关联', exact: true }).first(),
  ).toBeVisible()
  await spectrum.getByRole('button', { name: '接受关联', exact: true }).first().click()
  await expect(spectrum.getByRole('cell', { name: '已确认', exact: true }).first()).toBeVisible()
  await page.getByLabel('人工注释名称', { exact: true }).fill('Reviewed candidate')
  await page.getByRole('button', { name: '保存人工指定', exact: true }).click()
  await expect(spectrum.locator('.selected-peak')).toContainText('Reviewed candidate')
  await spectrum.getByLabel('谱图强度显示').selectOption('true')
  await expect(chart).toContainText('Relative abundance (%)')
  await spectrum.getByRole('button', { name: '恢复全谱', exact: true }).click()
  await spectrum.screenshot({ path: test.info().outputPath('annotation-spectrum.png') })
  await page.setViewportSize({ width: 390, height: 844 })
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
  await spectrum.screenshot({ path: test.info().outputPath('annotation-spectrum-mobile.png') })
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
  await page.getByLabel('脂质数据库文件').selectOption('preset:mammalian_cells')
  await expect(page.getByLabel('注释证据模式')).toHaveValue('true')
  await page.getByRole('button', { name: '运行精确质量候选注释', exact: true }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  await expect(spectrum.locator('.js-plotly-plot')).toBeVisible()
  await expect(spectrum.locator('.js-plotly-plot')).toContainText('Mean matrix value')
  await expect(spectrum.getByLabel('谱图强度显示')).toBeDisabled()
  await page.getByLabel('脂质逐特征核对', { exact: true }).selectOption('316.320225793')
  await expect(spectrum.locator('.selected-peak')).toContainText('SPB19:0;O2')
  await expect(page.getByRole('alert')).toHaveCount(0)
})
