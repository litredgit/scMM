import { createRouter, createWebHistory } from 'vue-router'
import ProjectsPage from '../features/projects/ProjectsPage.vue'
import SamplesPage from '../features/samples/SamplesPage.vue'
import ParametersPage from '../features/parameters/ParametersPage.vue'
import ResultsPage from '../features/results/ResultsPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/projects', component: ProjectsPage },
    { path: '/samples', component: SamplesPage },
    { path: '/parameters', component: ParametersPage },
    { path: '/results', component: ResultsPage },
  ],
})
