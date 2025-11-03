import { defineStore } from 'pinia'
import { ref } from 'vue'
import { login, logout, getCurrentUser, register } from '@/api/auth'
import { setToken, removeToken } from '@/utils/auth'
import { ElMessage } from 'element-plus'

export const useUserStore = defineStore('user', () => {
  const userInfo = ref(null)
  const loading = ref(false)

  // 登录
  const loginAction = async (loginForm) => {
    loading.value = true
    try {
      const response = await login(loginForm)
      setToken(response.access_token)
      await getUserInfo()
      ElMessage.success('登录成功')
      return true
    } catch (error) {
      console.error('Login failed:', error)
      return false
    } finally {
      loading.value = false
    }
  }

  // 注册
  const registerAction = async (registerForm) => {
    loading.value = true
    try {
      await register(registerForm)
      ElMessage.success('注册成功，请登录')
      return true
    } catch (error) {
      console.error('Register failed:', error)
      return false
    } finally {
      loading.value = false
    }
  }

  // 获取用户信息
  const getUserInfo = async () => {
    try {
      const response = await getCurrentUser()
      userInfo.value = response
      return response
    } catch (error) {
      console.error('Get user info failed:', error)
      removeToken()
      userInfo.value = null
      throw error
    }
  }

  // 登出
  const logoutAction = async () => {
    try {
      await logout()
      removeToken()
      userInfo.value = null
      ElMessage.success('已退出登录')
    } catch (error) {
      console.error('Logout failed:', error)
      // 即使接口失败也清除本地数据
      removeToken()
      userInfo.value = null
    }
  }

  return {
    userInfo,
    loading,
    loginAction,
    registerAction,
    getUserInfo,
    logoutAction
  }
})