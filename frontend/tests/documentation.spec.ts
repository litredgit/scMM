import { expect, navigate, test } from './fixtures'
import { importDataset } from './support/project'

test.use({ viewport: { width: 1920, height: 1080 } })

test('the guide opens at the current step and returns to the same editor draft', async ({
  page,
}) => {
  await importDataset(page, '文档阅读期间保留草稿')
  await navigate(page, '/data-editor')
  const draft = page.locator('input[aria-label$=" group"]').first()
  await draft.fill('未应用的样本分组')

  const button = page.getByRole('button', { name: '项目文档', exact: true })
  const panel = page.getByRole('dialog', { name: '项目文档' })
  const body = panel.getByRole('article')
  const scroll = await page.evaluate(() => {
    window.scrollTo(0, 320)
    return window.scrollY
  })
  await button.click()
  await expect(body.getByRole('heading', { name: '数据检查与数据编辑' })).toBeFocused()
  await body.getByRole('link', { name: '建立当前数据集', exact: true }).click()
  await expect(body.getByRole('heading', { name: '提取、停止与审核' })).toBeFocused()
  await expect(page).toHaveURL(/\/data-editor$/)

  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(button).toBeFocused()
  await expect(draft).toHaveValue('未应用的样本分组')
  expect(await page.evaluate(() => window.scrollY)).toBe(scroll)

  await navigate(page, '/preprocess')
  await button.click()
  await expect(body.getByRole('heading', { name: '预处理与 QC' })).toBeFocused()
  await panel.getByRole('button', { name: '关闭项目文档' }).click()
  await navigate(page, '/raw')
  await button.click()
  await expect(body.getByRole('heading', { name: '预览与应用参数' })).toBeFocused()
  await expect(page).toHaveURL(/\/raw$/)
})

test('four guide entries lead to rendered content and the appendix keeps the reference pages accessible', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: '项目文档', exact: true }).click()
  const panel = page.getByRole('dialog', { name: '项目文档' })
  const navigation = panel.getByRole('navigation', { name: '文档目录' })
  const body = panel.getByRole('article')
  await expect(navigation.getByRole('button')).toHaveText([
    '项目与数据',
    '细胞提取',
    '特征注释',
    '统计分析',
    '附录',
  ])
  await body.getByRole('link', { name: '文档导航' }).click()
  await expect(body.getByRole('heading', { name: '按任务阅读' })).toBeVisible()
  await body.getByRole('link', { name: '附录', exact: true }).click()
  await expect(body.getByRole('heading', { name: '附录', exact: true })).toBeFocused()
  await expect(body.getByRole('link', { name: '部署与运维' })).toBeVisible()
  await expect(body.getByRole('link', { name: '验证报告' })).toBeVisible()
  await body.getByRole('link', { name: '部署与运维' }).click()
  await expect(body.getByRole('heading', { name: '部署与运维', exact: true })).toBeFocused()
  await navigation.getByRole('button', { name: '附录', exact: true }).click()
  await body.getByRole('link', { name: '脂质规则审阅草案' }).click()
  await expect(body.getByRole('heading', { name: /脂质注释规则预设/ })).toBeFocused()
  await expect(body.getByRole('table').first()).toBeVisible()
  await expect(body.getByRole('link', { name: 'pbmc.review-v1.json' })).toHaveAttribute(
    'href',
    /github\.com\/litredgit\/scMM\/blob\/main\/scMM\/resources\/lipid_rules\/pbmc\.review-v1\.json$/,
  )
  await body.getByRole('link', { name: '附录', exact: true }).click()
  await body.getByRole('link', { name: '上游统计方法评估' }).click()
  await expect(body.locator('pre code')).toContainText('Σ(Y - P)²')

  await navigation.getByRole('button', { name: '特征注释', exact: true }).click()
  await expect(body.getByRole('heading', { name: '特征注释', exact: true })).toBeFocused()
  await navigation.getByRole('button', { name: '细胞提取', exact: true }).click()
  await body.getByRole('link', { name: 'SNR 图解', exact: true }).first().click()
  await expect(body.getByRole('heading', { name: '从原始谱到细胞与特征矩阵' })).toBeFocused()
  await expect(body.locator('strong').filter({ hasText: 'SNR 提取' }).first()).toBeVisible()
  const diagram = body.getByRole('img', { name: /处理流程：原始扫描/ })
  await expect(diagram).toBeInViewport()
  await expect
    .poll(() => diagram.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0)
  await page.screenshot({ path: test.info().outputPath('project-documentation-desktop.png') })
  await panel
    .getByRole('navigation', { name: '本页章节' })
    .getByRole('button', { name: '网页默认参数与适用范围' })
    .click()
  await expect(body.getByRole('heading', { name: '网页默认参数与适用范围' })).toBeFocused()
})

test('document fetch failures can be retried from the reading panel', async ({ page }) => {
  let fail = true
  await page.route('**/assets/projects-and-data-*.md', async (route) => {
    if (fail) await route.abort('failed')
    else await route.continue()
  })
  await page.goto('/')
  await page.getByRole('button', { name: '项目文档', exact: true }).click()
  const panel = page.getByRole('dialog', { name: '项目文档' })
  await expect(panel.getByRole('alert')).toContainText('文档加载失败')
  fail = false
  await panel.getByRole('button', { name: '重试' }).click()
  await expect(panel.getByRole('heading', { name: '登录与工作区' })).toBeFocused()
  await expect(panel.getByRole('alert')).toHaveCount(0)
})
