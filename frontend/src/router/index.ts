import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import RecomputeFrontierView from '@/views/RecomputeFrontierView.vue'
import ScheduleDetailView from '@/views/ScheduleDetailView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/recompute-frontier', name: 'recompute-frontier', component: RecomputeFrontierView },
    {
      path: '/query_scheduler/recompute/:batchId',
      name: 'recompute-schedule',
      component: ScheduleDetailView,
      props: true,
    },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
