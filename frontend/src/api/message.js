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