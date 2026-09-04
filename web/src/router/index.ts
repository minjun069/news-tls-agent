import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'issues',
      component: () => import('../views/IssueListView.vue'),
    },
    {
      path: '/issues/:issueId',
      name: 'issue-detail',
      component: () => import('../views/IssueDetailView.vue'),
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

export default router
