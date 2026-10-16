import { test, expect } from './fixtures'
import { readFile } from 'node:fs/promises'

test('lipid rules, isotope review, filtered adduct CSV and saved versions', async ({ page }) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('脂质标记验收')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '导入已有结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ lipids.h5ad/ }).click()
  await page.getByRole('button', { name: '导入结果', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
  await page.getByRole('link', { name: /预处理/ }).click()
  const panel = page.locator('.lipid-panel')
  await expect(panel.getByRole('heading', { name: '注释与同位素', exact: true })).toBeVisible()
  await expect(panel).not.toHaveAttribute('open', '')
  await expect(panel.getByRole('button', { name: '检查本地数据库' })).not.toBeVisible()
  expect(
    await page.getByRole('heading', { name: '历史与恢复' }).evaluate((heading) => {
      const panel = document.querySelector('.lipid-panel')!
      return Boolean(heading.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING)
    }),
  ).toBe(true)
  await panel.locator(':scope > summary').click()
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
  await expect(page.getByRole('status')).toHaveText('规则已校验，可保存预设或应用排序。')
  await expect(rulePreview.getByRole('row')).toHaveCount(3)
  await page.getByLabel('脂质预设名称', { exact: true }).fill('浏览器规则')
  await page.getByRole('button', { name: '保存为规则预设', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('规则已保存为预设。')
  await page.getByLabel('脂质规则预设', { exact: true }).selectOption('浏览器规则')
  await expect(page.getByLabel('脂质规则预设', { exact: true }).locator('option')).toHaveCount(7)
  await page.getByLabel('脂质版本名称').fill('第一次标记')
  await page.getByRole('button', { name: '运行注释与同位素标记', exact: true }).dblclick()
  await expect(panel.getByText('4 / 4 特征 · 4 条候选 · 4 条关系证据')).toBeVisible()
  await expect(page.getByLabel('脂质查看版本').locator('option')).toHaveCount(2)
  await expect(
    panel.getByRole('row').filter({ hasText: 'Synthetic lipid A' }).first(),
  ).toBeVisible()
  await expect(
    panel.getByRole('row').filter({ hasText: 'Synthetic lipid B' }).first(),
  ).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
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
  expect(csv.split('\n')[0]).toBe(',f_h,f_unknown')
  expect(csv.trim().split('\n')).toHaveLength(41)
  await page.getByLabel('加合物保留方式', { exact: true }).selectOption('specified')
  await panel.getByLabel('[M+Na]+', { exact: true }).last().check()
  await page.getByRole('button', { name: '应用显示筛选', exact: true }).click()
  downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: '导出筛选矩阵 CSV', exact: true }).click()
  download = await downloadPromise
  csv = await readFile((await download.path())!, 'utf8')
  expect(csv.split('\n')[0]).toBe(',f_na,f_unknown')

  await page.getByLabel('加合物保留方式', { exact: true }).selectOption('all')
  await page.getByLabel('同位素状态', { exact: true }).selectOption('all')
  await page.getByRole('button', { name: '应用显示筛选', exact: true }).click()
  await page.getByLabel('脂质逐特征核对', { exact: true }).selectOption('f_h')
  await panel.getByLabel('指定 LMGP01010002 [M+H]+', { exact: true }).uncheck()
  await page.getByRole('button', { name: '保存人工指定', exact: true }).click()
  await expect(page.getByRole('status')).toHaveText('人工指定已保存。')
  await panel.getByRole('button', { name: '接受', exact: true }).first().click()
  await expect(panel.getByRole('cell', { name: '接受', exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '保存项目', exact: true }).first().click()
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('link', { name: 'scMM 项目首页' }).click()
  await page
    .getByRole('row')
    .filter({ hasText: '脂质标记验收' })
    .getByRole('button', { name: '打开项目 →' })
    .click()
  await expect(page).toHaveURL(/\/samples$/)
  await page.getByRole('link', { name: /预处理/ }).click()
  await expect(panel).not.toHaveAttribute('open', '')
  await panel.locator(':scope > summary').click()
  await expect(panel.getByText('4 / 4 特征 · 4 条候选 · 4 条关系证据')).toBeVisible()
  await page.getByLabel('脂质逐特征核对', { exact: true }).selectOption('f_h')
  await expect(panel.getByLabel('指定 LMGP01010001 [M+H]+', { exact: true })).toBeChecked()
  await expect(panel.getByLabel('指定 LMGP01010002 [M+H]+', { exact: true })).not.toBeChecked()
  await expect(panel.getByRole('cell', { name: '接受', exact: true }).first()).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(errors).toEqual([])
})
