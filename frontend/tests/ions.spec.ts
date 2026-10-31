import { test, expect, type Page } from './fixtures'

async function openIons(page: Page, name: string) {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill(name)
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^(?:▤ )?lipids[.]h5ad\s/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await page.getByRole('link', { name: /^4\s*预处理$/ }).click()
  await page.getByRole('link', { name: '离子归组与注释（统计预处理前）' }).click()
  await page.getByLabel('起点数值空间').selectOption('linear_abundance')
  await page.getByRole('button', { name: '启用离子数据目录' }).click()
  await expect(page.getByRole('heading', { name: '1. 候选关系与竞争解释' })).toBeVisible()
}
async function read(page: Page, path: string) {
  const workspace = await page.evaluate(() => sessionStorage.getItem('scmm-workspace')!)
  const response = await page.request.get(`/api/v1/workspace${path}`, {
    headers: { 'X-SCMM-Workspace': workspace },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return response.json()
}

test('manual ion review, quantitative views, candidate overlay and complete export', async ({
  page,
}) => {
  test.setTimeout(90000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await openIons(page, '离子合成贯通')
  await page.getByLabel('离子形式', { exact: true }).selectOption(['[M+H]+', '[M+Na]+'])
  await page.getByRole('button', { name: '后台生成候选与解释' }).click()
  await expect(page.getByRole('button', { name: '收集结果' })).toBeVisible({ timeout: 20000 })
  await page.reload()
  await expect(page.getByRole('button', { name: '收集结果' })).toBeVisible()
  await page.getByRole('button', { name: '收集结果' }).click()
  const info = await read(page, '/ions/info')
  const version = info.versions[0].id
  const current = await read(page, '')
  const result = await read(
    page,
    `/ions/download?kind=version&key=${version}&revision=${current.revision}`,
  )
  const group = result.grouping.groups.find(
    (row: { feature_ids: string[] }) => row.feature_ids.length === 3,
  )
  const hypothesis = group.hypotheses.find(
    (row: { members: Record<string, { species_id: string; isotope_shift: number }> }) =>
      row.members.f_h.species_id === '[M+H]+' &&
      row.members.f_h.isotope_shift === 0 &&
      row.members.f_iso.isotope_shift > 0,
  )
  const relations = result.grouping.relations
    .filter(
      (row: {
        left_feature_id: string
        right_feature_id: string
        kind: string
        charge_magnitude: number
      }) =>
        group.feature_ids.includes(row.left_feature_id) &&
        group.feature_ids.includes(row.right_feature_id) &&
        (['adduct'].includes(row.kind) || (row.kind === 'isotope' && row.charge_magnitude === 1)),
    )
    .map((row: { relation_id: string }) => row.relation_id)
  await page.getByLabel('EC ID', { exact: true }).fill(group.ec_id)
  await page.getByLabel('离子角色解释', { exact: true }).fill(hypothesis.hypothesis_id)
  await page.getByLabel('支持关系 ID（逗号分隔）', { exact: true }).fill(relations.join(','))
  await page.getByLabel('审阅理由', { exact: true }).fill('Synthetic fixture; known construction')
  await page.getByRole('button', { name: '接受所列关系与此组解释' }).click()
  await page.getByRole('button', { name: '建立来源视图与分析分支' }).click()
  await expect(page.getByLabel('分析视图与分支')).toHaveCount(1)
  const latest = await read(page, '/ions/info')
  const compound = latest.views.find((row: { level: string }) => row.level === 'L2')
  const branch = latest.branches.find((row: { view_id: string }) => row.view_id === compound.id)
  await page.getByLabel('分析视图与分支').selectOption(branch.id)
  await page.getByRole('button', { name: '切换分析分支' }).click()
  await expect(page.getByLabel('分析视图与分支')).toHaveValue(branch.id)
  await page
    .getByLabel('候选库内容', { exact: true })
    .fill('[{"record_id":"x","name":"synthetic","formula":"C10H20"}]')
  await page.getByRole('button', { name: '搜索质量与已有公式候选' }).click()
  await expect.poll(async () => (await read(page, '/ions/info')).annotation_versions.length).toBe(1)
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载完整离子项目包' }).click()
  expect((await download).suggestedFilename()).toBe('ion-project.zip')
  await page.getByRole('link', { name: '进入统计预处理', exact: true }).click()
  await expect(page.getByLabel('分析视图与分支')).toHaveValue(branch.id)
  expect(errors).toEqual([])
})

test('ion page remains usable on a narrow viewport and invalid JSON reports an error', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openIons(page, '离子窄屏')
  await page.getByLabel('候选库内容', { exact: true }).fill('invalid JSON')
  await page.getByRole('button', { name: '搜索质量与已有公式候选' }).click()
  await expect(page.getByText(/Unexpected token|JSON/).first()).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBeTruthy()
})
