import { test, expect } from './fixtures'

test('six workflow steps navigate in both directions and guard missing data', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('步骤切换验收')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  const navigation = page.getByRole('navigation', { name: '步骤切换', exact: true })
  await expect(navigation.getByRole('button', { name: /上一步：项目首页/ })).toBeEnabled()
  await navigation.getByRole('button', { name: /下一步：原始谱与参数/ }).click()
  await expect(page).toHaveURL(/\/raw$/)
  await navigation.getByRole('button', { name: /下一步：提取与审核/ }).click()
  await expect(page).toHaveURL(/\/extraction$/)
  await expect(navigation.getByRole('button', { name: /下一步：预处理/ })).toBeDisabled()
  await expect(navigation.getByText(/请先审核纳入提取结果/)).toBeVisible()
  await navigation.getByRole('button', { name: /上一步：原始谱与参数/ }).click()
  await navigation.getByRole('button', { name: /上一步：项目与样本/ }).click()
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
  for (const target of ['raw', 'extraction', 'preprocess', 'analysis', 'results']) {
    await navigation.getByRole('button', { name: /下一步：/ }).click()
    await expect(page).toHaveURL(new RegExp(`/${target}$`))
    await expect(page.getByRole('alert')).toHaveCount(0)
  }
  await expect(navigation.getByRole('button', { name: /下一步：/ })).toHaveCount(0)
  for (const target of ['analysis', 'preprocess', 'extraction', 'raw', 'samples', 'projects']) {
    await navigation.getByRole('button', { name: /上一步：/ }).click()
    await expect(page).toHaveURL(new RegExp(`/${target}$`))
  }
  await expect(navigation).toHaveCount(0)
  expect(errors).toEqual([])
})

test('each workflow page restores its own scroll and first visits start at top', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1366, height: 768 })
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('逐页滚动')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('link', { name: /原始谱与参数/ }).click()
  await expect(page.getByRole('heading', { name: '原始谱与参数', exact: true })).toBeVisible()
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            window.scrollTo(0, 400)
            resolve()
          }),
        ),
      ),
  )
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(100)
  const rawPosition = await page.evaluate(() => scrollY)
  // DOM clicks avoid Playwright first scrolling the sidebar link into view.
  await page
    .getByRole('link', { name: /提取与审核/ })
    .evaluate((el: HTMLAnchorElement) => el.click())
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(0)
  await page
    .getByRole('link', { name: /原始谱与参数/ })
    .evaluate((el: HTMLAnchorElement) => el.click())
  await expect.poll(() => page.evaluate(() => scrollY)).toBe(rawPosition)
})

test('project drafts survive workspace refresh and saving does not apply them', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill('草稿状态')
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByLabel('项目说明', { exact: true }).fill('尚未应用的说明')
  await expect(page.locator('.draft-state')).toContainText('项目信息')
  await page.getByRole('button', { name: '保存项目', exact: true }).click()
  await expect(page.getByLabel('项目说明', { exact: true })).toHaveValue('尚未应用的说明')
  await expect(page.locator('.draft-state')).toContainText('项目信息')
  await expect(page.locator('.save-state')).toHaveText('已保存')
  await page.getByRole('button', { name: '应用项目信息', exact: true }).click()
  await expect(page.locator('.save-state')).toHaveText('已应用未保存')
  await expect(page.locator('.draft-state')).toHaveCount(0)
})
