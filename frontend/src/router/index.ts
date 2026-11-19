import { nextTick } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ProjectsPage from '../features/projects/ProjectsPage.vue'
import SamplesPage from '../features/samples/SamplesPage.vue'
import ParametersPage from '../features/parameters/ParametersPage.vue'
import ResultsPage from '../features/results/ResultsPage.vue'

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
    { path: '/projects', component: ProjectsPage },
    {
      path: '/cell-extraction',
      component: () => import('../features/modules/ModuleHome.vue'),
      props: { module: 'extraction' },
    },
    { path: '/annotation', component: () => import('../features/modules/AnnotationPage.vue') },
    {
      path: '/annotation/evidence',
      component: () => import('../features/annotation/AnnotationEvidencePage.vue'),
    },
    {
      path: '/statistics',
      component: () => import('../features/modules/ModuleHome.vue'),
      props: { module: 'statistics' },
    },
    { path: '/admin/monitor', component: () => import('../features/monitor/MonitorPage.vue') },
    { path: '/account', component: () => import('../features/account/AccountPage.vue') },
    { path: '/samples', component: SamplesPage },
    { path: '/parameters', component: ParametersPage },
    { path: '/results', component: ResultsPage },
    { path: '/raw', component: () => import('../features/raw/RawPage.vue') },
    { path: '/extraction', component: () => import('../features/extraction/ExtractionPage.vue') },
    { path: '/data-check', component: () => import('../features/preprocess/DataInspection.vue') },
    {
      path: '/data-editor',
      component: () => import('../features/preprocess/DataInspection.vue'),
      props: { editor: true },
    },
    { path: '/preprocess', component: () => import('../features/preprocess/PreprocessPage.vue') },
    { path: '/ions', component: () => import('../features/ions/IonsPage.vue') },
    { path: '/analysis', component: () => import('../features/analysis/AnalysisPage.vue') },
  ],
})

router.beforeEach((_to, from) => {
  positions.set(from.path, { left: window.scrollX, top: window.scrollY })
})
