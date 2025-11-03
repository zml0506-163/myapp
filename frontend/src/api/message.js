import request from './request'

/**
 * 获取对话消息列表
 */
export function getMessages(conversationId) {
  return request({
    url: `/conversations/${conversationId}/messages`,
    method: 'get'
  })
}

/**
 * 发送消息
 */
export function sendMessage(conversationId, data) {
  return request({
    url: `/conversations/${conversationId}/messages`,
    method: 'post',
    data
  })
}

/**
 * 流式 AI 回复（SSE）
 */
export function streamChat(conversationId, content, attachments = []) {
  const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
  const token = localStorage.getItem('token')
  
  const eventSource = new EventSource(
    `${baseURL}/chat/stream?conversation_id=${conversationId}&content=${encodeURIComponent(content)}&token=${token}`
  )
  
  return eventSource
}