import { test, expect, type Page } from './fixtures'
import { readFile } from 'node:fs/promises'
import { createProject as create, importDataset as importData } from './support/project'

test.use({ actionTimeout: 15000 })

async function noError(page: Page) {
  await expect(page.getByRole('alert')).toHaveCount(0)
}

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
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText(
    '所选内容已移入共享回收区。',
  )
  await expect(retention).toHaveCount(0)
  await page.getByText('共享回收区（1）', { exact: true }).click()
  await page.getByRole('button', { name: '恢复', exact: true }).click()
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText('已恢复到原位置。')
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
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText(
    '策略清单已移入共享回收区，尚未释放磁盘空间。',
  )
  await page.getByRole('button', { name: '查看快照与缓存保留计划', exact: true }).click()
  await expect(retention).toContainText('当前没有快照或缓存条目。')
  await page.getByText(/^共享回收区（/).click()
  const entry = page.getByRole('row').filter({ hasText: '快照与缓存策略清理' })
  await entry.getByRole('button', { name: '恢复', exact: true }).click()
  await expect(page.locator('.workspace-feedback[role="status"]')).toHaveText('已恢复到原位置。')
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
  await expect(page.locator('.workspace-feedback[role="status"]')).toContainText('已停用自动保留')
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
