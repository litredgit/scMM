import { expect, type Page } from '@playwright/test'
export async function createProject(page: Page, name: string) {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill(name)
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
}
export async function importDataset(page: Page, name: string) {
  await createProject(page, name)
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toBeVisible()
}
