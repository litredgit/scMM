import { nextTick } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ProjectsPage from '../features/projects/ProjectsPage.vue'
import SamplesPage from '../features/samples/SamplesPage.vue'
import ParametersPage from '../features/parameters/ParametersPage.vue'
import ResultsPage from '../features/results/ResultsPage.vue'

declare module 'vue-router' {
  interface RouteMeta {
    assistantPage?: string
  }
}

const positions = new Map<string, { left: number; top: number }>()
export function resetScrollPositions() {
  positions.clear()
  window.scrollTo(0, 0)
}
export const router = createRouter({
  history: createWebHistory(),
  async scrollBehavior(to, _from, saved) {
    await nextTick()
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    return saved ?? positions.get(to.path) ?? { left: 0, top: 0 }
  },
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/projects', component: ProjectsPage, meta: { assistantPage: 'projects' } },
    {
      path: '/cell-extraction',
      component: () => import('../features/modules/ModuleHome.vue'),
      props: { module: 'extraction' },
      meta: { assistantPage: 'cell-extraction' },
    },
    {
      path: '/annotation',
      component: () => import('../features/modules/AnnotationPage.vue'),
      meta: { assistantPage: 'annotation' },
    },
    {
      path: '/annotation/evidence',
      component: () => import('../features/annotation/AnnotationEvidencePage.vue'),
      meta: { assistantPage: 'annotation-evidence' },
    },
    {
      path: '/statistics',
      component: () => import('../features/modules/ModuleHome.vue'),
      props: { module: 'statistics' },
      meta: { assistantPage: 'statistics' },
    },
    { path: '/admin/monitor', component: () => import('../features/monitor/MonitorPage.vue') },
    {
      path: '/account',
      component: () => import('../features/account/AccountPage.vue'),
      meta: { assistantPage: 'account' },
    },
    { path: '/samples', component: SamplesPage, meta: { assistantPage: 'samples' } },
    { path: '/parameters', component: ParametersPage, meta: { assistantPage: 'parameters' } },
    { path: '/results', component: ResultsPage, meta: { assistantPage: 'results' } },
    {
      path: '/raw',
      component: () => import('../features/raw/RawPage.vue'),
      meta: { assistantPage: 'raw' },
    },
    {
      path: '/extraction',
      component: () => import('../features/extraction/ExtractionPage.vue'),
      meta: { assistantPage: 'extraction' },
    },
    {
      path: '/data-check',
      component: () => import('../features/preprocess/DataInspection.vue'),
      meta: { assistantPage: 'data-check' },
    },
    {
      path: '/data-editor',
      component: () => import('../features/preprocess/DataInspection.vue'),
      props: { editor: true },
      meta: { assistantPage: 'data-editor' },
    },
    {
      path: '/preprocess',
      component: () => import('../features/preprocess/PreprocessPage.vue'),
      meta: { assistantPage: 'preprocess' },
    },
    {
      path: '/ions',
      component: () => import('../features/ions/IonsPage.vue'),
      meta: { assistantPage: 'ions' },
    },
    {
      path: '/analysis',
      component: () => import('../features/analysis/AnalysisPage.vue'),
      meta: { assistantPage: 'analysis' },
    },
  ],
})

router.beforeEach((_to, from) => {
  positions.set(from.path, { left: window.scrollX, top: window.scrollY })
})
