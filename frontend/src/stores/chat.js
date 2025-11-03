import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  getConversations,
  createConversation,
  updateConversation,
  deleteConversation
} from '@/api/conversation'
import {
  getMessages,
  sendMessage
} from '@/api/message'
import { ElMessage } from 'element-plus'

export const useChatStore = defineStore('chat', () => {
  const conversations = ref([])
  const currentConversationId = ref(null)
  const messages = ref([])
  const loading = ref(false)

  // 获取对话列表
  const fetchConversations = async () => {
    loading.value = true
    try {
      const data = await getConversations()
      conversations.value = data
    } catch (error) {
      console.error('Fetch conversations failed:', error)
    } finally {
      loading.value = false
    }
  }

  // 创建新对话
  const createNewConversation = async (title = '新对话') => {
    try {
      const conversation = await createConversation({ title })
      conversations.value.unshift(conversation)
      currentConversationId.value = conversation.id
      messages.value = []
      return conversation
    } catch (error) {
      console.error('Create conversation failed:', error)
      ElMessage.error('创建对话失败')
      throw error
    }
  }

  // 切换对话
  const switchConversation = async (conversationId) => {
    if (currentConversationId.value === conversationId) return
    
    currentConversationId.value = conversationId
    await fetchMessages(conversationId)
  }

  // 获取对话消息
  const fetchMessages = async (conversationId) => {
    loading.value = true
    try {
      const data = await getMessages(conversationId)
      messages.value = data
    } catch (error) {
      console.error('Fetch messages failed:', error)
      ElMessage.error('获取消息失败')
    } finally {
      loading.value = false
    }
  }

  // 发送消息
  const sendUserMessage = async (content, attachments = []) => {
    if (!currentConversationId.value) {
      ElMessage.warning('请先选择或创建对话')
      return
    }

    try {
      const message = await sendMessage(currentConversationId.value, {
        content,
        message_type: 'user',
        conversation_id: currentConversationId.value,
        attachments
      })
      
      messages.value.push(message)
      
      // 更新对话列表中的时间戳
      const conv = conversations.value.find(c => c.id === currentConversationId.value)
      if (conv) {
        conv.updated_at = new Date().toISOString()
        // 将对话移到列表顶部
        conversations.value = [
          conv,
          ...conversations.value.filter(c => c.id !== currentConversationId.value)
        ]
      }
      
      return message
    } catch (error) {
      console.error('Send message failed:', error)
      ElMessage.error('发送消息失败')
      throw error
    }
  }

  // 接收 AI 消息
  const receiveAIMessage = (content) => {
    const aiMessage = {
      id: Date.now(),
      content,
      message_type: 'assistant',
      conversation_id: currentConversationId.value,
      created_at: new Date().toISOString(),
      attachments: []
    }
    messages.value.push(aiMessage)
    return aiMessage
  }

  // 重命名对话
  const renameConversation = async (conversationId, title) => {
    try {
      const updated = await updateConversation(conversationId, { title })
      const index = conversations.value.findIndex(c => c.id === conversationId)
      if (index !== -1) {
        conversations.value[index] = { ...conversations.value[index], ...updated }
      }
      ElMessage.success('重命名成功')
    } catch (error) {
      console.error('Rename conversation failed:', error)
      ElMessage.error('重命名失败')
      throw error
    }
  }

  // 删除对话
  const removeConversation = async (conversationId) => {
    try {
      await deleteConversation(conversationId)
      conversations.value = conversations.value.filter(c => c.id !== conversationId)
      
      // 如果删除的是当前对话，切换到第一个对话
      if (currentConversationId.value === conversationId) {
        if (conversations.value.length > 0) {
          await switchConversation(conversations.value[0].id)
        } else {
          currentConversationId.value = null
          messages.value = []
        }
      }
      
      ElMessage.success('删除成功')
    } catch (error) {
      console.error('Delete conversation failed:', error)
      ElMessage.error('删除失败')
      throw error
    }
  }

  return {
    conversations,
    currentConversationId,
    messages,
    loading,
    fetchConversations,
    createNewConversation,
    switchConversation,
    fetchMessages,
    sendUserMessage,
    receiveAIMessage,
    renameConversation,
    removeConversation
  }
})