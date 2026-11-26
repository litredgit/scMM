import { test, expect } from '@playwright/test'
import { closeDocument } from './fixtures'

test.afterEach(async ({ page }) => closeDocument(page))
test.use({ viewport: { width: 1920, height: 1080 } })

test('login, private workspace, team account refresh and logout', async ({ page, context }) => {
  test.setTimeout(60000)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'scMM 工作台' })).toBeVisible()
  expect((await context.request.get('/api/v1/projects')).status()).toBe(401)
  const configuration = Promise.withResolvers<void>()
  const configurationRequested = Promise.withResolvers<void>()
  await page.route(
    '**/api/v1/configuration',
    async (route) => {
      configurationRequested.resolve()
      await configuration.promise
      await route.continue()
    },
    { times: 1 },
  )
  await page.getByLabel('账号', { exact: true }).fill('browser')
  await page
    .getByLabel('密码', { exact: true })
    .fill(process.env.SCMM_E2E_PASSWORD ?? 'Synthetic browser passphrase')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await configurationRequested.promise
  await page.getByRole('link', { name: '账号与管理' }).click()
  const team = page.getByRole('region', { name: '团队管理' })
  const accounts = team.getByRole('table').filter({
    has: page.getByRole('columnheader', { name: '角色', exact: true }),
  })
  const adminRow = accounts
    .getByRole('row')
    .filter({ has: page.getByRole('cell', { name: 'browser', exact: true }) })
  try {
    await expect(adminRow.getByRole('cell', { name: '正常', exact: true })).toBeVisible()
    await expect(team.getByRole('button', { name: '创建账号', exact: true })).toBeDisabled()
  } finally {
    configuration.resolve()
  }
  const state = await page.evaluate(async () => await (await fetch('/api/v1/auth/me')).json())
  await page.getByLabel('新账号名称').fill('browser-member')
  const creation = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/admin/users') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  const created = await creation
  expect(created.status()).toBe(201)
  const { id: memberId } = await created.json()
  const credential = await page.getByLabel('一次性凭据', { exact: true }).inputValue()
  expect(credential.length).toBeGreaterThan(32)
  const memberRow = accounts
    .getByRole('row')
    .filter({ has: page.getByRole('cell', { name: 'browser-member', exact: true }) })
  await expect(memberRow.getByRole('cell', { name: '待设置密码', exact: true })).toBeVisible()
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
  await member.locator('.account-menu > summary').click()
  await member.getByRole('button', { name: '退出登录' }).click()
  await expect(member.getByRole('button', { name: '登录', exact: true })).toBeVisible()
  expect(
    (await other.request.get(page.url().replace('/account', '/api/v1/projects'))).status(),
  ).toBe(401)
  await closeDocument(member)
  await other.close()

  await page.getByRole('link', { name: '项目首页', exact: true }).first().click()
  await expect(page.getByLabel('项目名称', { exact: true })).toBeVisible()
  const disabled = await context.request.patch(`/api/v1/admin/users/${memberId}`, {
    headers: { 'X-SCMM-Client': 'web', 'X-SCMM-CSRF': state.csrf },
    data: { active: false },
  })
  expect(disabled.ok()).toBeTruthy()
  await page.route('**/api/v1/admin/users', (route) => route.fulfill({ status: 503 }), { times: 1 })
  await page.getByRole('link', { name: '账号与管理' }).click()
  await expect(team.getByRole('alert')).toContainText('团队账号读取失败')
  await team.getByRole('button', { name: '重新读取团队账号' }).click()
  await expect(memberRow.getByRole('cell', { name: '已停用', exact: true })).toBeVisible()
  await expect(adminRow.getByRole('cell', { name: '正常', exact: true })).toBeVisible()

  await team.getByLabel('新账号名称').fill('BROWSER-MEMBER')
  const conflict = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/admin/users') && response.request().method() === 'POST',
  )
  await team.getByRole('button', { name: '创建账号', exact: true }).click()
  expect((await conflict).status()).toBe(409)
  await expect(page.getByText('账号已存在。', { exact: true })).toBeVisible()
  await expect(memberRow).toHaveCount(1)
})
