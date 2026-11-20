import { navigate, test, expect, type Page } from './fixtures'

test.use({ viewport: { width: 1920, height: 1080 } })

async function openIons(page: Page, name: string) {
  await page.goto('/')
  await page.getByLabel('项目名称', { exact: true }).fill(name)
  await page.getByRole('button', { name: '创建并添加样本' }).click()
  await page.getByRole('button', { name: '导入 H5AD 数据', exact: true }).click()
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await page.getByRole('button', { name: /^(?:▤ )?lipids[.]h5ad\s/ }).click()
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await navigate(page, '/preprocess')
  await navigate(page, '/annotation')
  await page.getByRole('button', { name: '生成离子关系', exact: true }).click()
  await page.getByLabel('起点数值空间').selectOption('linear_abundance')
  await page.getByRole('button', { name: '启用离子数据目录' }).click()
  await expect(page.getByRole('heading', { name: '生成离子关系与竞争解释' })).toBeVisible()
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
  await page.getByRole('button', { name: '生成离子关系', exact: true }).click()
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
  await page.getByLabel('查看内容').selectOption('groups')
  await page.getByRole('button', { name: new RegExp(group.ec_id.slice(0, 8)) }).click()
  await page.getByLabel('离子角色解释', { exact: true }).selectOption(hypothesis.hypothesis_id)
  for (const id of relations) await page.getByLabel('组内支持关系 ' + id, { exact: true }).check()
  await page.getByLabel('审阅理由', { exact: true }).fill('Synthetic fixture; known construction')
  await page.getByRole('button', { name: '接受所列关系与此组解释' }).click()
  await navigate(page, '/ions')
  await page.getByRole('button', { name: '预览 L1 / L2', exact: true }).click()
  await expect(page.getByText('预览结果与代表离子', { exact: true })).toBeVisible()
  const previewInfo = await read(page, '/ions/info')
  expect(previewInfo.views.map((view: { level: string }) => view.level)).toEqual(['L0'])
  await page.getByRole('button', { name: '建立来源视图与分析分支' }).click()
  await expect(page.getByLabel('分析视图与分支')).toHaveCount(1)
  const latest = await read(page, '/ions/info')
  const compound = latest.views.find((row: { level: string }) => row.level === 'L2')
  const branch = latest.branches.find((row: { view_id: string }) => row.view_id === compound.id)
  await page.getByLabel('分析视图与分支').selectOption(branch.id)
  await page.getByRole('button', { name: '作为统计输入' }).click()
  await expect(page.getByLabel('分析视图与分支')).toHaveValue(branch.id)
  await expect.poll(async () => (await read(page, '/ions/info')).active_branch_id).toBe(branch.id)
  await navigate(page, '/annotation')
  await expect(page.locator('.annotation-context')).toContainText(/统计输入\s*L2/)
  await expect(page.getByLabel('谱图来源')).toContainText('L0 测量根')
  await page.getByRole('button', { name: '查看完整谱图', exact: true }).click()
  const spectrum = page.getByRole('region', { name: '谱图注释与关联峰' })
  await expect(spectrum.locator('.js-plotly-plot')).toContainText('Full feature spectrum')
  const graph = spectrum.locator('.js-plotly-plot')
  const markerIndex = await graph.evaluate((element) => {
    const traces = (element as HTMLElement & { data: { customdata?: string[][] }[] }).data
    return traces
      .flatMap((trace) => trace.customdata ?? [])
      .findIndex((item) => item[0] === 'f_iso')
  })
  expect(markerIndex).toBeGreaterThanOrEqual(0)
  await graph
    .locator('.scatterlayer .trace .points path.point')
    .nth(markerIndex)
    .click({ force: true })
  await expect(spectrum.locator('.selected-peak')).toContainText('选中 f_iso')
  await spectrum.getByRole('button', { name: '返回局部谱图', exact: true }).click()
  await expect(spectrum.locator('.selected-peak')).toContainText('选中 f_iso')
  expect((await read(page, '/ions/info')).active_branch_id).toBe(branch.id)
  await page.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByText('使用本地化合物库', { exact: true }).click()
  await page
    .getByLabel('候选库内容', { exact: true })
    .fill('[{"record_id":"x","name":"synthetic","formula":"C10H20"}]')
  await page.getByRole('button', { name: '搜索质量与已有公式候选' }).click()
  await expect.poll(async () => (await read(page, '/ions/info')).annotation_versions.length).toBe(1)
  await navigate(page, '/ions')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载完整离子项目包' }).click()
  expect((await download).suggestedFilename()).toBe('ion-project.zip')
  await page.getByRole('link', { name: '进入统计预处理', exact: true }).click()
  await expect(page.getByLabel('分析视图与分支')).toHaveValue(branch.id)
  expect(errors).toEqual([])
})

test('the workbench reports an invalid local compound library inline', async ({ page }) => {
  await openIons(page, '化合物库错误反馈')
  await page.getByRole('button', { name: '查找候选', exact: true }).click()
  await page.getByText('使用本地化合物库', { exact: true }).click()
  await page.getByLabel('候选库内容', { exact: true }).fill('invalid JSON')
  await page.getByRole('button', { name: '搜索质量与已有公式候选' }).click()
  await expect(page.getByText(/Unexpected token|JSON/).first()).toBeVisible()
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBeTruthy()
})
