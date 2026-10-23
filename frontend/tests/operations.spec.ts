import { test, expect, type Page } from './fixtures'
import { readFile } from 'node:fs/promises'
import { createProject as create } from './support/project'
import { serialPolling } from '../src/api/polling'
import type { useWorkspace } from '../src/stores/workspace'

test.use({ actionTimeout: 15000 })

async function noError(page: Page) {
  await expect(page.getByRole('alert')).toHaveCount(0)
}

test('explicit result selection, detailed help, stable QC and readable narrow layout', async ({
  page,
}) => {
  test.setTimeout(60000)
  await create(page, '界面说明与默认结果')
  await page.getByRole('button', { name: '导入独立结果', exact: true }).click()
  const listing = await page.request.get('/api/v1/storage/entries?root=Results&kind=results')
  const latest = (await listing.json()).latest.name as string
  await page.getByLabel('服务器存储', { exact: true }).selectOption('Results')
  await expect(page.getByText(`已选结果：${latest}`, { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导入并替换当前数据', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: /^▤ analysis.h5ad/ }).click()
  await expect(page.getByText('已选结果：analysis.h5ad', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '结果与样本关联' })).toHaveCount(0)
  await page.getByRole('button', { name: '检查所选结果', exact: true }).click()
  await page.getByRole('button', { name: '导入并替换当前数据', exact: true }).click()
  await page.getByRole('link', { name: /预处理/ }).click()
  const helper = page.getByRole('button', { name: 'min_detected说明', exact: true })
  await helper.hover()
  await expect(page.getByRole('tooltip')).toContainText('等于阈值保留')
  await expect(page.getByRole('tooltip')).toContainText('不重做峰检出')
  await helper.focus()
  await expect(page.getByRole('tooltip')).toBeVisible()
  await helper.press('Escape')
  await expect(page.getByRole('tooltip')).toHaveCount(0)
  await page.getByLabel('下一项操作', { exact: true }).selectOption('normalize')
  await page.getByText('查看全部 normalization 方法', { exact: true }).click()
  await expect(page.locator('.method-list .help-trigger')).toHaveCount(7)
  await page.getByLabel('normalization', { exact: true }).selectOption('log')
  await expect(page.locator('.method-help > p')).toContainText('零值变为')
  await page.getByLabel('normalization', { exact: true }).selectOption('total')
  await page.getByRole('button', { name: '应用到当前数据', exact: true }).click()
  await expect(page.getByText(/横轴采用稳定范围/)).toBeVisible()
  await expect
    .poll(() =>
      page
        .locator('.js-plotly-plot')
        .first()
        .evaluate(
          (el) =>
            (el as HTMLElement & { _fullLayout: { xaxis: { range: number[] } } })._fullLayout.xaxis
              .range,
        ),
    )
    .toEqual([0.95, 1.05])
  expect(await page.evaluate(() => getComputedStyle(document.body).fontSize)).toBe('16px')
  const plotSize = await page
    .locator('.js-plotly-plot')
    .first()
    .evaluate((el) => ({ width: el.clientWidth, height: el.clientHeight }))
  for (const format of ['SVG', 'PNG']) {
    const wait = page.waitForEvent('download')
    await page.getByRole('button', { name: `下载 ${format}`, exact: true }).click()
    const download = await wait
    const bytes = await readFile((await download.path())!)
    if (format === 'PNG') {
      expect(bytes.readUInt32BE(16)).toBe(Math.floor((89 / 25.4) * 300))
      expect(bytes.readUInt32BE(20)).toBe(Math.floor((65 / 25.4) * 300))
    } else {
      const svg = bytes.toString('utf8')
      const width = Number(svg.match(/<svg[^>]* width="([\d.]+)"/)?.[1])
      const height = Number(svg.match(/<svg[^>]* height="([\d.]+)"/)?.[1])
      expect(width / height).toBeCloseTo(89 / 65, 2)
    }
  }

  await page.screenshot({ path: test.info().outputPath('preprocess-1440.png'), fullPage: true })
  for (const width of [700, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await expect
      .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
      .toBe(true)
    await expect
      .poll(() =>
        page
          .locator('.js-plotly-plot')
          .first()
          .evaluate(
            (el) =>
              Math.abs(
                el.getBoundingClientRect().width -
                  (el as HTMLElement & { _fullLayout: { width: number } })._fullLayout.width,
              ) < 2,
          ),
      )
      .toBe(true)
    await page.screenshot({
      path: test.info().outputPath(`preprocess-${width}.png`),
      fullPage: true,
    })
  }
  await noError(page)
})

test('serial polling coalesces refreshes and resume waits for the old read to settle', async () => {
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let calls = 0
  let concurrent = 0
  let maximum = 0
  const publications: boolean[] = []
  const polling = serialPolling(
    async (isCurrent) => {
      calls++
      concurrent++
      maximum = Math.max(maximum, concurrent)
      if (calls === 1) await held
      publications.push(isCurrent())
      concurrent--
    },
    60_000,
    (cause) => {
      throw cause
    },
  )
  try {
    polling.start()
    await expect.poll(() => calls).toBe(1)
    const first = polling.refresh()
    expect(polling.refresh()).toBe(first)
    polling.stop()
    polling.start()
    expect(calls).toBe(1)
    release()
    await first
    await expect.poll(() => calls).toBe(2)
    expect(maximum).toBe(1)
    expect(publications).toEqual([false, true])
  } finally {
    release()
    polling.stop()
  }
})

test('serial polling reports current errors once and can read again without replaying a write', async () => {
  const errors: unknown[] = []
  let calls = 0
  const polling = serialPolling(
    async () => {
      calls++
      if (calls === 1) throw new Error('合成读取失败')
    },
    60_000,
    (cause) => errors.push(cause),
  )
  try {
    polling.start(false)
    await polling.refresh()
    expect(errors).toHaveLength(1)
    await polling.refresh()
    expect(calls).toBe(2)
    expect(errors).toHaveLength(1)
  } finally {
    polling.stop()
  }
})

test('stopping before a poll starts prevents the request and stale failures are ignored', async () => {
  const errors: unknown[] = []
  let calls = 0
  let reject!: (cause: unknown) => void
  const held = new Promise<void>((_, fail) => {
    reject = fail
  })
  const polling = serialPolling(
    async () => {
      calls++
      await held
    },
    60_000,
    (cause) => errors.push(cause),
  )
  polling.start()
  polling.stop()
  await Promise.resolve()
  expect(calls).toBe(0)
  polling.start()
  await expect.poll(() => calls).toBe(1)
  const pending = polling.refresh()
  polling.stop()
  reject(new Error('停用后的失败'))
  await pending
  expect(errors).toEqual([])
})

test('duplicate extraction review cannot report success or clear the running phase before the request finishes', async ({
  page,
}) => {
  await page.route('**/workspace/extraction/batches', (route) =>
    route.fulfill({
      json: [
        {
          path: '/synthetic/batch/state',
          status: 'completed',
          created_at: '2026-10-22T00:00:00Z',
          message: '合成批次',
          samples: [
            { id: 'synthetic-a', name: '待审核输入', status: 'succeeded', cells: 2, features: 1 },
          ],
        },
      ],
    }),
  )
  await create(page, '重复审核操作')
  await page.getByRole('link', { name: /提取与审核/ }).click()
  await page.getByLabel('待审核输入 · 2 细胞', { exact: true }).check()
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const pending = new Promise<void>((resolve) => {
    entered = resolve
  })
  let requests = 0
  await page.route('**/workspace/extraction/review', async (route) => {
    requests++
    entered()
    await held
    await route.fulfill({ status: 400, json: { error: { message: '合成审核失败，未建立数据' } } })
  })
  try {
    await page.getByRole('button', { name: '建立当前数据集', exact: true }).evaluate((button) => {
      // Two already queued events before Vue patches disabled must share the same guard.
      ;(button as HTMLButtonElement).click()
      ;(button as HTMLButtonElement).click()
    })
    await pending
    expect(requests).toBe(1)
    await expect(
      page.getByText('当前数据集已建立，可进入预处理。项目仍需主动保存。', { exact: true }),
    ).toHaveCount(0)
    await expect(page.getByText('正在合并所选样本并建立当前数据集…', { exact: true })).toBeVisible()
    release()
    await expect(page.getByRole('alert')).toContainText('合成审核失败，未建立数据')
    await expect(
      page.getByText('当前数据集已建立，可进入预处理。项目仍需主动保存。', { exact: true }),
    ).toHaveCount(0)
  } finally {
    release()
  }
})

test('a delayed background read cannot overwrite the failure of a later save', async ({ page }) => {
  let release!: () => void
  const held = new Promise<void>((resolve) => {
    release = resolve
  })
  let entered!: () => void
  const pending = new Promise<void>((resolve) => {
    entered = resolve
  })
  await page.route('**/workspace/extraction/batches', async (route) => {
    entered()
    await held
    await route.fulfill({ status: 400, json: { error: { message: '旧的后台读取失败' } } })
  })
  await page.route('**/workspace/project/save', (route) =>
    route.fulfill({ status: 400, json: { error: { message: '本次项目保存失败' } } }),
  )
  try {
    await create(page, '操作反馈归属')
    await pending
    await page.getByRole('button', { name: '保存项目', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('本次项目保存失败')
    const response = page.waitForResponse((r) => r.url().endsWith('/extraction/batches'))
    release()
    await response
    await page.waitForTimeout(100)
    await expect(page.getByRole('alert')).toContainText('本次项目保存失败')
    await expect(page.getByRole('alert')).not.toContainText('旧的后台读取失败')
  } finally {
    release()
  }
})

test('operation outcomes distinguish skipped, stale, failed and void success without releasing a newer operation', async ({
  page,
}) => {
  await create(page, '操作返回语义')
  const result = await page.evaluate(async () => {
    // Access the running Pinia store to exercise its public action contract.
    const root = document.getElementById('app') as HTMLElement & {
      __vue_app__: {
        config: {
          globalProperties: { $pinia: { _s: Map<string, ReturnType<typeof useWorkspace>> } }
        }
      }
    }
    const store = root.__vue_app__.config.globalProperties.$pinia._s.get('workspace')!
    let releaseOld!: () => void
    const oldGate = new Promise<void>((resolve) => {
      releaseOld = resolve
    })
    const old = store.run(async (scope) => {
      await oldGate
      scope.update({ label: '旧操作不得发布', phase: 'failed' })
      return '旧值'
    }, '旧成功不得发布')
    let submitted = 0
    const skipped = await store.run(async () => {
      submitted++
      return '重复操作'
    })
    store.reset()
    let releaseNew!: () => void
    const newGate = new Promise<void>((resolve) => {
      releaseNew = resolve
    })
    const newer = store.run(async (scope) => {
      scope.update({ label: '新操作', phase: 'collecting' })
      await newGate
      return '新值'
    }, '新操作成功')
    releaseOld()
    const stale = await old
    const whileNew = {
      busy: store.busy,
      label: store.operation?.label,
      phase: store.operation?.phase,
      notice: store.notice,
      error: store.error,
    }
    releaseNew()
    const succeeded = await newer
    const successNotice = store.notice
    const failed = await store.run(async () => {
      throw new Error('当前操作失败')
    }, '不得发布的成功')
    const failure = {
      busy: store.busy,
      phase: store.operation?.phase,
      error: store.error,
      notice: store.notice,
    }
    const empty = await store.run(async () => undefined)
    return {
      submitted,
      skipped,
      stale,
      whileNew,
      succeeded,
      successNotice,
      failed,
      failure,
      emptyStatus: empty.status,
    }
  })
  expect(result.submitted).toBe(0)
  expect(result.skipped.status).toBe('skipped')
  expect(result.stale.status).toBe('stale')
  expect(result.whileNew).toEqual({
    busy: true,
    label: '新操作',
    phase: 'collecting',
    notice: '',
    error: '',
  })
  expect(result.succeeded).toEqual({ status: 'succeeded', value: '新值' })
  expect(result.successNotice).toBe('新操作成功')
  expect(result.failed).toEqual({ status: 'failed', error: '当前操作失败' })
  expect(result.failure).toEqual({
    busy: false,
    phase: 'failed',
    error: '当前操作失败',
    notice: '',
  })
  expect(result.emptyStatus).toBe('succeeded')
})

for (const waitAt of ['response', 'blob'] as const) {
  test(`a previous workspace download cannot publish after reset while waiting for ${waitAt}`, async ({
    page,
  }) => {
    await create(page, `下载来源-${waitAt}`)
    let entered!: () => void
    const pending = new Promise<void>((resolve) => {
      entered = resolve
    })
    let release!: () => void
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    let downloads = 0
    page.on('download', () => {
      downloads++
    })
    if (waitAt === 'blob') {
      await page.exposeFunction('scmmTestBlobRead', () => entered())
      await page.evaluate(() => {
        const original = Response.prototype.blob
        Response.prototype.blob = async function () {
          if (this.url.includes('/workspace/results/download')) {
            const continued = new Promise<void>((resolve) =>
              window.addEventListener('scmm-test-continue-blob', () => resolve(), { once: true }),
            )
            await (window as unknown as { scmmTestBlobRead(): Promise<void> }).scmmTestBlobRead()
            await continued
          }
          return original.call(this)
        }
      })
    }
    await page.route('**/workspace/results/download?*', async (route) => {
      if (waitAt === 'response') {
        entered()
        await held
      }
      await route.fulfill({
        contentType: 'text/csv',
        body: 'feature,value\nf0,1.123456789012345\n',
      })
    })
    const result = page.evaluate(async () => {
      const root = document.getElementById('app') as HTMLElement & {
        __vue_app__: {
          config: {
            globalProperties: { $pinia: { _s: Map<string, ReturnType<typeof useWorkspace>> } }
          }
        }
      }
      return root.__vue_app__.config.globalProperties.$pinia._s
        .get('workspace')!
        .download('matrix', 'late.csv')
    })
    try {
      await pending
      await page.evaluate(() => {
        const root = document.getElementById('app') as HTMLElement & {
          __vue_app__: {
            config: {
              globalProperties: { $pinia: { _s: Map<string, ReturnType<typeof useWorkspace>> } }
            }
          }
        }
        root.__vue_app__.config.globalProperties.$pinia._s.get('workspace')!.reset()
        window.dispatchEvent(new Event('scmm-test-continue-blob'))
      })
      release()
      expect((await result)?.status).toBe('stale')
      expect(downloads).toBe(0)
      await expect(page.getByRole('alert')).toHaveCount(0)
    } finally {
      release()
    }
  })
}
