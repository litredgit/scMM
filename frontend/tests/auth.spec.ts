import { test, expect } from '@playwright/test'

test('login, private workspace, account management, reset and logout', async ({
  page,
  context,
}) => {
  test.setTimeout(60000)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'scMM 工作台' })).toBeVisible()
  expect((await context.request.get('/api/v1/projects')).status()).toBe(401)
  await page.getByLabel('账号', { exact: true }).fill('browser')
  await page
    .getByLabel('密码', { exact: true })
    .fill(process.env.SCMM_E2E_PASSWORD ?? 'Synthetic browser passphrase')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByLabel('项目名称', { exact: true })).toBeVisible()
  const state = await page.evaluate(async () => await (await fetch('/api/v1/auth/me')).json())
  await page.getByRole('link', { name: '账号与管理' }).click()
  await page.getByLabel('新账号名称').fill('browser-member')
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  const credential = await page.getByLabel('一次性凭据', { exact: true }).inputValue()
  expect(credential.length).toBeGreaterThan(32)
  await page.getByRole('button', { name: '关闭凭据显示' }).click()
  await expect(page.getByLabel('一次性凭据', { exact: true })).toHaveCount(0)
  const other = await context.browser()!.newContext()
  const member = await other.newPage()
  await member.goto(page.url().replace('/account', '/'))
  await member.getByLabel('账号', { exact: true }).fill('browser-member')
  await member.getByLabel('密码', { exact: true }).fill(credential)
  await member.getByRole('button', { name: '登录', exact: true }).click()
  await expect(member.getByLabel('新密码', { exact: true })).toBeVisible()
  const memberPassword = 'Synthetic member passphrase'
  await member.getByLabel('新密码', { exact: true }).fill(memberPassword)
  await member.getByLabel('再次输入新密码').fill(memberPassword)
  await member.getByRole('button', { name: '设置密码', exact: true }).click()
  await member.getByLabel('账号', { exact: true }).fill('browser-member')
  await member.getByLabel('密码', { exact: true }).fill(memberPassword)
  await member.getByRole('button', { name: '登录', exact: true }).click()
  await expect(member.getByLabel('项目名称', { exact: true })).toBeVisible()
  expect(
    (await other.request.get(page.url().replace('/account', '/api/v1/admin/users'))).status(),
  ).toBe(403)
  expect(
    (await other.request.get(page.url().replace('/account', '/api/v1/admin/monitor'))).status(),
  ).toBe(403)
  expect(state.role).toBe('admin')
  await member.getByRole('button', { name: '退出登录' }).click()
  await expect(member.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  expect(
    (await other.request.get(page.url().replace('/account', '/api/v1/projects'))).status(),
  ).toBe(401)
  await other.close()
})
