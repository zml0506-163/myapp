import request from './request'

/**
 * 获取对话列表
 */
export function getConversations(params) {
  return request({
    url: '/conversations',
    method: 'get',
    params
  })
}

/**
 * 创建对话
 */
export function createConversation(data) {
  return request({
    url: '/conversations',
    method: 'post',
    data
  })
}

/**
 * 获取对话详情
 */
export function getConversation(id) {
  return request({
    url: `/conversations/${id}`,
    method: 'get'
  })
}

/**
 * 更新对话（重命名）
 */
export function updateConversation(id, data) {
  return request({
    url: `/conversations/${id}`,
    method: 'put',
    data
  })
}

/**
 * 删除对话
 */
export function deleteConversation(id) {
  return request({
    url: `/conversations/${id}`,
    method: 'delete'
  })
}