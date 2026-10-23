import { test, expect } from './fixtures'
import { createProject, importDataset } from './support/project'

for (const selection of ['switch', 'aba', 'resume'] as const) {
  for (const lateFailure of [false, true]) {
    test(`same revision figure selection ${selection} rejects late ${lateFailure ? 'failure' : 'success'}`, async ({
      page,
    }) => {
      await importDataset(page, `结果图响应-${selection}-${lateFailure}`)
      await page.route('**/workspace/analysis', async (route) => {
        const response = await route.fetch()
        await route.fulfill({
          json: { ...(await response.json()), figures: ['scope_A', 'scope_B'] },
        })
      })
      await page.getByRole('link', { name: /结果与保存/ }).click()
      let release!: () => void
      const held = new Promise<void>((resolve) => {
        release = resolve
      })
      let entered!: () => void
      const pending = new Promise<void>((resolve) => {
        entered = resolve
      })
      await page.route('**/analysis/figures/scope_*', async (route) => {
        const isOld = route.request().url().endsWith('scope_A')
        if (isOld) {
          entered()
          await held
        }
        await route.fulfill(
          isOld && lateFailure
            ? { status: 400, json: { error: { message: '已切换图形的旧错误' } } }
            : {
                json: {
                  data: [
                    { type: 'scatter', x: [0, 1], y: [1, 2], name: isOld ? 'OLD_A' : 'CURRENT_B' },
                  ],
                  layout: { showlegend: true },
                },
              },
        )
      })
      try {
        await page.getByLabel('已保存图形', { exact: true }).selectOption('scope_A')
        await page.getByRole('button', { name: '查看图形', exact: true }).click()
        await pending
        if (selection === 'resume') {
          await page.getByRole('link', { name: /项目与样本/ }).click()
          await page.getByRole('link', { name: /结果与保存/ }).click()
          await expect(page.getByLabel('已保存图形', { exact: true })).toHaveValue('scope_A')
        } else {
          await page.getByLabel('已保存图形', { exact: true }).selectOption('scope_B')
          await page.getByRole('button', { name: '查看图形', exact: true }).click()
          await expect(page.locator('.legendtext').filter({ hasText: 'CURRENT_B' })).toBeVisible()
          if (selection === 'aba')
            await page.getByLabel('已保存图形', { exact: true }).selectOption('scope_A')
        }
        const response = page.waitForResponse((r) => r.url().endsWith('/figures/scope_A'))
        release()
        await response
        await page.waitForTimeout(100)
        if (selection === 'switch')
          await expect(page.locator('.legendtext').filter({ hasText: 'CURRENT_B' })).toBeVisible()
        else await expect(page.locator('.plot-shell')).toHaveCount(0)
        await expect(page.locator('.legendtext').filter({ hasText: 'OLD_A' })).toHaveCount(0)
        await expect(page.getByRole('alert')).toHaveCount(0)
      } finally {
        release()
      }
    })
  }
}

for (const saveFirst of [false, true]) {
  test(`delayed preset defaults preserve restored selection and a newer JSON draft: saved=${saveFirst}`, async ({
    page,
  }) => {
    await createProject(page, '预设恢复读取')
    await page.getByRole('link', { name: /原始谱与参数/ }).click()
    const workspace = await page.evaluate(() => sessionStorage.getItem('scmm-workspace')!)
    const state = await (
      await page.request.get('/api/v1/workspace', { headers: { 'X-SCMM-Workspace': workspace } })
    ).json()
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let loaded = false,
      restored = false
    await page.route('**/api/v1/preferences', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON()
        return route.fulfill({ json: { presets: body.presets, selected: body.selected } })
      }
      loaded = true
      await held
      await route.fulfill({
        json: {
          presets: { 'global-default': 150, 'saved-draft': 151 },
          selected: 'global-default',
        },
      })
    })
    await page.route('**/workspace/maintenance/draft', async (route) => {
      if (route.request().method() !== 'GET') return route.continue()
      restored = true
      await route.fulfill({
        json: {
          project_path: state.project.path,
          route: '/raw',
          forms: {},
          views: { raw: { preset: 'saved-draft' } },
        },
      })
    })
    try {
      await page.reload()
      await expect.poll(() => loaded && restored).toBe(true)
      await expect(page.getByRole('heading', { name: '原始谱与参数', exact: true })).toBeVisible()
      // The maintenance protocol applies deferred controls after 200ms.
      await page.waitForTimeout(250)
      await page.getByRole('button', { name: '展开全部参数', exact: true }).click()
      await page.getByRole('tab', { name: '参考预设', exact: true }).click()
      const draft = '{"saved-draft":151,"new-draft":152}'
      await page.getByLabel('预设名称与参考 m/z（JSON）', { exact: true }).fill(draft)
      if (saveFirst) {
        await page.getByRole('button', { name: '保存全局预设', exact: true }).click()
        await expect(
          page.getByText('全局预设已保存；已有项目参数由明确应用决定。', { exact: true }),
        ).toBeVisible()
      }
      const response = page.waitForResponse(
        (r) => r.url().endsWith('/preferences') && r.request().method() === 'GET',
      )
      release()
      await response
      await expect(page.getByLabel('Cell type', { exact: true })).toHaveValue('saved-draft')
      await expect(page.getByLabel('预设名称与参考 m/z（JSON）', { exact: true })).toHaveValue(
        draft,
      )
      if (saveFirst)
        await expect(
          page
            .getByLabel('Cell type', { exact: true })
            .locator('option')
            .filter({ hasText: 'new-draft' }),
        ).toHaveCount(1)
    } finally {
      release()
    }
  })
}

for (const resume of [false, true]) {
  test(`preset read failure is visible and retryable without duplicate initial requests: resume=${resume}`, async ({
    page,
  }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    let reads = 0
    await page.route('**/api/v1/preferences', (route) => {
      reads++
      return route.fulfill(
        reads === 1
          ? { status: 400, json: { error: { message: '合成预设读取失败' } } }
          : { json: { presets: { loaded: 150 }, selected: 'loaded' } },
      )
    })
    await createProject(page, '预设读取重试')
    await page.getByRole('link', { name: /原始谱与参数/ }).click()
    await expect(page.getByRole('alert')).toContainText('合成预设读取失败')
    expect(reads).toBe(1)
    if (resume) {
      await page.getByRole('link', { name: /项目与样本/ }).click()
      await page.getByRole('link', { name: /原始谱与参数/ }).click()
    } else await page.getByRole('button', { name: '重试读取预设', exact: true }).click()
    await expect(page.getByLabel('Cell type', { exact: true }).locator('option')).toHaveText([
      'loaded · 150',
    ])
    await expect(page.getByRole('alert')).toHaveCount(0)
    expect(reads).toBe(2)
    expect(errors).toEqual([])
  })
}

test('project metadata reads coalesce and cannot replace a newer save failure after leaving the page', async ({
  page,
}) => {
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const pending = new Promise<void>((resolve) => {
    entered = resolve
  })
  let requests = 0
  await page.route('**/api/v1/projects', async (route) => {
    requests++
    entered()
    await held
    await route.fulfill({ status: 400, json: { error: { message: '已离开页面的项目列表错误' } } })
  })
  await page.route('**/workspace/project/save', (route) =>
    route.fulfill({ status: 400, json: { error: { message: '本次保存失败需保留' } } }),
  )
  try {
    await page.goto('/')
    await pending
    await page.getByLabel('项目名称', { exact: true }).fill('项目列表并发读取')
    await page.getByRole('button', { name: '创建并添加样本' }).click()
    await expect(page.getByRole('heading', { name: '项目与样本', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '保存项目', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('本次保存失败需保留')
    const response = page.waitForResponse((r) => r.url().endsWith('/api/v1/projects'))
    release()
    await response
    await page.waitForTimeout(100)
    await expect(page.getByRole('alert')).toContainText('本次保存失败需保留')
    expect(requests).toBe(1)
  } finally {
    release()
  }
})

test('a parameter read retried after page resume preserves edits made while its first read was pending', async ({
  page,
}) => {
  await createProject(page, '参数草稿与读取')
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const pending = new Promise<void>((resolve) => {
    entered = resolve
  })
  let reads = 0
  await page.route('**/workspace/parameters', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    const response = await route.fetch()
    reads++
    entered()
    await held
    await route.fulfill({ response })
  })
  try {
    await page.getByRole('link', { name: /原始谱与参数/ }).click()
    await pending
    await page.getByLabel('cell_min_signal', { exact: true }).fill('42')
    await page.getByRole('link', { name: /项目与样本/ }).click()
    await page.getByRole('link', { name: /原始谱与参数/ }).click()
    await expect.poll(() => reads).toBe(2)
    const response = page.waitForResponse(
      (r) => r.url().endsWith('/workspace/parameters') && r.request().method() === 'GET',
    )
    release()
    await response
    await page.waitForTimeout(100)
    await expect(page.getByLabel('cell_min_signal', { exact: true })).toHaveValue('42')
    await expect(page.getByLabel('参数生效状态')).toContainText('与所选范围的生效配置不同')
    await expect(page.getByRole('alert')).toHaveCount(0)
  } finally {
    release()
  }
})

for (const lateFailure of [false, true]) {
  test(`feature search ignores its previous same-revision ${lateFailure ? 'failure' : 'success'}`, async ({
    page,
  }) => {
    await importDataset(page, `特征搜索身份-${lateFailure}`)
    await page.getByRole('link', { name: /^5\s*分析$/ }).click()
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let entered!: () => void
    const pending = new Promise<void>((resolve) => {
      entered = resolve
    })
    await page.route('**/analysis/features?*', async (route) => {
      const query = new URL(route.request().url()).searchParams.get('query')
      if (query === 'held') {
        entered()
        await held
        await route.fulfill(
          lateFailure
            ? { status: 400, json: { error: { message: '旧特征搜索错误' } } }
            : { json: { rows: [{ value: 'f0', label: 'OLD_FEATURE' }], total: 1 } },
        )
      } else if (query === 'current')
        await route.fulfill({
          json: { rows: [{ value: 'f0', label: 'CURRENT_FEATURE' }], total: 1 },
        })
      else await route.continue()
    })
    try {
      await page.getByLabel('Color source', { exact: true }).selectOption('feature')
      await page.getByLabel('Search', { exact: true }).fill('held')
      await pending
      await page.getByLabel('Search', { exact: true }).fill('current')
      await expect(page.getByLabel('Color', { exact: true }).locator('option')).toContainText([
        'CURRENT_FEATURE',
      ])
      const response = page.waitForResponse((r) => r.url().includes('query=held'))
      release()
      await response
      await page.waitForTimeout(100)
      await expect(page.getByLabel('Color', { exact: true }).locator('option')).toContainText([
        'CURRENT_FEATURE',
      ])
      await expect(page.getByRole('alert')).toHaveCount(0)
    } finally {
      release()
    }
  })
}

for (const lateFailure of [false, true]) {
  test(`a resumed extraction signal view ignores an earlier ${lateFailure ? 'failure' : 'success'}`, async ({
    page,
  }) => {
    await page.route('**/workspace/extraction/batches', (route) =>
      route.fulfill({
        json: [
          {
            path: '/synthetic/batch/state',
            status: 'completed',
            created_at: '2026-10-23T00:00:00Z',
            message: '信号查询',
            samples: [{ id: 'a', name: '样本 A', status: 'succeeded', cells: 2, features: 1 }],
          },
        ],
      }),
    )
    await createProject(page, `信号查询来源-${lateFailure}`)
    await page.getByRole('link', { name: /提取与审核/ }).click()
    await page.getByLabel('审核信号样本', { exact: true }).selectOption('a')
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let entered!: () => void
    const pending = new Promise<void>((resolve) => {
      entered = resolve
    })
    await page.route('**/workspace/extraction/signal', async (route) => {
      const response = await page.request.get('/api/v1/workspace', {
        headers: route.request().headers(),
      })
      const workspace = await response.json()
      entered()
      await held
      await route.fulfill(
        lateFailure
          ? { status: 400, json: { error: { message: '旧审核信号错误' } } }
          : {
              json: {
                workspace,
                value: {
                  figure: {
                    data: [{ type: 'scatter', x: [0], y: [1], name: 'OLD_SIGNAL' }],
                    layout: {},
                  },
                },
              },
            },
      )
    })
    try {
      await page.getByRole('button', { name: '查看完整信号', exact: true }).click()
      await pending
      await page.getByRole('link', { name: /项目与样本/ }).click()
      await page.getByRole('link', { name: /提取与审核/ }).click()
      const response = page.waitForResponse((r) => r.url().endsWith('/extraction/signal'))
      release()
      await response
      await page.waitForTimeout(100)
      await expect(page.locator('.plot-shell')).toHaveCount(0)
      await expect(page.getByRole('alert')).toHaveCount(0)
    } finally {
      release()
    }
  })
}
