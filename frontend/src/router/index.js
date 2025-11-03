import { createRouter, createWebHistory } from 'vue-router'
import { isAuthenticated } from '@/utils/auth'
import Chat from '../views/Chat.vue' // 导入聊天页面

const routes = [
    {
        path: '/login',
        name: 'Login',
        component: () => import('@/views/Login.vue'),
        meta: { requiresAuth: false }
    },
    {
        path: '/register',
        name: 'Register',
        component: () => import('@/views/Register.vue'),
        meta: { requiresAuth: false }
    },
    {
        path: '/chat', // 访问路径：http://localhost:5173/chat
        name: 'Chat',
        component: Chat,
        meta: { requiresAuth: true }
    },
    {
        path: '/search',
        name: 'SearchPubMed',
        component: () => import('@/views/SearchPubMed.vue') ,
        meta: { requiresAuth: false }
    },
    // 可以添加其他页面路由
    {
        path: '/',
        redirect: '/chat' // 默认跳转到聊天页面
    }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
    const authenticated = isAuthenticated()
    
    if (to.meta.requiresAuth && !authenticated) {
      // 需要登录但未登录，跳转到登录页
      next({ name: 'Login', query: { redirect: to.fullPath } })
    } else if (!to.meta.requiresAuth && authenticated && (to.name === 'Login' || to.name === 'Register')) {
      // 已登录访问登录/注册页，跳转到首页
      next({ name: 'Chat' })
    } else {
      next()
    }
  })
  
  export default router