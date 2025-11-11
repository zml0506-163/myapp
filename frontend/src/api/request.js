import axios from 'axios'
import { ElMessage } from 'element-plus'
import { getToken, removeToken } from '@/utils/auth'
import router from '@/router'

// 创建 axios 实例
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
service.interceptors.response.use(
  response => {
    // 如果是blob类型，直接返回数据（用于文件下载）
    if (response.config.responseType === 'blob') {
      return response.data
    }
    return response.data
  },
  error => {
    console.error('Response error:', error)
    
    const { response, config } = error
    
    if (response) {
      const { status, data } = response
      
      switch (status) {
        case 401:
          // 区分登录接口和其他接口的401错误
          if (config.url && config.url.includes('/auth/login')) {
            // 登录接口的401，显示后端返回的具体错误信息
            ElMessage.error(data?.detail || '登录验证失败，请输入正确的账号密码')
          } else {
            // 其他接口的401，说明token过期
            ElMessage.error('登录已过期，请重新登录')
            removeToken()
            router.push('/login')
          }
          break
        case 403:
          ElMessage.error('没有权限访问')
          break
        case 404:
          ElMessage.error('请求的资源不存在')
          break
        case 413:
          ElMessage.error('文件太大，上传失败')
          break
        case 500:
          ElMessage.error('服务器错误')
          break
        default:
          ElMessage.error(data?.detail || '请求失败')
      }
    } else if (error.request) {
      ElMessage.error('网络错误，请检查网络连接')
    } else {
      ElMessage.error('请求配置错误')
    }
    
    return Promise.reject(error)
  }
)

export default service