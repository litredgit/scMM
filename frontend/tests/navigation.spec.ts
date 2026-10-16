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
  await page.getByRole('button', { name: '导入已有结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await page.getByRole('button', { name: '导入结果', exact: true }).click()
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
