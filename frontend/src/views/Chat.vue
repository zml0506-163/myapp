<template>
  <div class="chat-container">
    <!-- 侧边栏 -->
    <div :class="['sidebar', { collapsed: !sidebarOpen }]">
      <!-- 侧边栏内容省略，与原来相同 -->
    </div>

    <!-- 主聊天区域 -->
    <div class="main-content">
      <!-- 头部 -->
      <div class="chat-header">
        <div class="toggle-sidebar-btn" @click="sidebarOpen = !sidebarOpen">
          <el-icon :size="20"><Fold /></el-icon>
        </div>
        <h1>{{ getCurrentChatTitle() }}</h1>
        
        <!-- 模式选择器 -->
        <div class="chat-mode-selector">
          <el-select v-model="chatMode" placeholder="选择对话模式" style="width: 200px">
            <el-option label="普通问答" value="normal" />
            <el-option label="附件问答" value="attachment" :disabled="attachments.length === 0" />
            <el-option label="多源检索" value="multi_source" />
          </el-select>
        </div>
      </div>

      <!-- 消息区域 -->
      <div class="chat-main" ref="chatMainRef">
        <div v-if="!chatStore.currentConversationId" class="empty-state">
          <el-empty description="请选择或创建一个对话开始聊天" />
        </div>
        
        <div v-else class="messages-wrapper">
          <!-- 消息列表 -->
          <div
            v-for="message in chatStore.messages"
            :key="message.id"
            :class="['message-item', message.message_type === 'user' ? 'user-message' : 'assistant-message']"
          >
            <div :class="['avatar', message.message_type === 'user' ? 'user-avatar' : 'assistant-avatar']">
              <el-icon :size="20">
                <User v-if="message.message_type === 'user'" />
                <ChatDotRound v-else />
              </el-icon>
            </div>

            <div class="message-content">
              <div :class="['message-bubble', message.message_type === 'user' ? 'user-bubble' : 'assistant-bubble']">
                <!-- 使用 Markdown 渲染 -->
                <div class="message-text" v-html="renderMarkdown(message.content)"></div>
                
                <!-- 附件显示 -->
                <div v-if="message.attachments && message.attachments.length > 0" class="message-attachments">
                  <el-tag
                    v-for="att in message.attachments"
                    :key="att.id"
                    :type="message.message_type === 'user' ? 'info' : 'success'"
                    size="small"
                  >
                    <el-icon style="margin-right: 4px"><Paperclip /></el-icon>
                    {{ att.original_filename }}
                  </el-tag>
                </div>
              </div>
            </div>
          </div>
          
          <!-- AI 正在输入 -->
          <div v-if="isAITyping" class="message-item assistant-message">
            <div class="avatar assistant-avatar">
              <el-icon :size="20"><ChatDotRound /></el-icon>
            </div>
            <div class="message-content">
              <div class="message-bubble assistant-bubble">
                <div class="message-text" v-html="renderMarkdown(currentAIMessage)"></div>
                <div class="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区域 -->
      <div class="chat-footer">
        <div class="input-wrapper">
          <!-- 附件预览 -->
          <div v-if="attachments.length > 0" class="attachments-preview">
            <el-tag
              v-for="att in attachments"
              :key="att.id"
              closable
              @close="removeAttachment(att.id)"
              type="primary"
            >
              <el-icon style="margin-right: 4px"><Paperclip /></el-icon>
              {{ att.original_filename }} ({{ formatFileSize(att.file_size) }})
            </el-tag>
          </div>

          <!-- 输入框 -->
          <div class="input-area">
            <div class="textarea-wrapper">
              <textarea
                ref="textareaRef"
                v-model="inputValue"
                placeholder="发送消息给 AI 助手..."
                @keydown="handleKeyDown"
                @input="adjustTextareaHeight"
                :disabled="!chatStore.currentConversationId || isSending"
                class="custom-textarea"
              ></textarea>
              
              <div class="textarea-toolbar">
                <div class="toolbar-left">
                  <!-- 上传按钮 -->
                  <el-upload
                    ref="uploadRef"
                    :auto-upload="false"
                    :on-change="handleFileChange"
                    :show-file-list="false"
                    multiple
                    :disabled="!chatStore.currentConversationId || isSending"
                    accept=".pdf,.png,.jpg,.jpeg,.webp"
                  >
                    <el-button text title="上传附件" :disabled="!chatStore.currentConversationId || isSending">
                      <el-icon><Paperclip /></el-icon>
                    </el-button>
                  </el-upload>
                </div>
                
                <div class="toolbar-right">
                  <!-- 发送按钮 -->
                  <el-button
                    type="primary"
                    :disabled="(!inputValue.trim() && attachments.length === 0) || !chatStore.currentConversationId"
                    :loading="isSending"
                    @click="handleSend"
                    class="send-btn"
                  >
                    <el-icon v-if="!isSending"><Promotion /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>

          <p class="input-hint">
            按 Enter 发送，Ctrl + Enter 换行 | 
            当前模式: <strong>{{ getModeLabel() }}</strong>
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  User,
  ChatDotRound,
  Paperclip,
  Promotion,
  Plus,
  Fold
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useChatStore } from '@/stores/chat'
import { uploadFile } from '@/api/upload'

const router = useRouter()
const userStore = useUserStore()
const chatStore = useChatStore()

// 状态
const inputValue = ref('')
const attachments = ref([])
const sidebarOpen = ref(true)
const chatMainRef = ref(null)
const textareaRef = ref(null)
const isSending = ref(false)
const isAITyping = ref(false)
const currentAIMessage = ref('')
const chatMode = ref('normal') // 'normal' | 'attachment' | 'multi_source'

// 初始化
onMounted(async () => {
  try {
    if (!userStore.userInfo) {
      await userStore.getUserInfo()
    }
    
    await chatStore.fetchConversations()
    
    if (chatStore.conversations.length > 0 && !chatStore.currentConversationId) {
      await chatStore.switchConversation(chatStore.conversations[0].id)
    }
  } catch (error) {
    console.error('初始化失败:', error)
    ElMessage.error('加载数据失败，请刷新页面重试')
  }
})

// Markdown 渲染
const renderMarkdown = (content) => {
  if (!content) return ''
  const html = marked.parse(content)
  return DOMPurify.sanitize(html)
}

// 获取模式标签
const getModeLabel = () => {
  const labels = {
    'normal': '普通问答',
    'attachment': '附件问答',
    'multi_source': '多源检索'
  }
  return labels[chatMode.value] || '普通问答'
}

// 滚动到底部
const scrollToBottom = () => {
  nextTick(() => {
    if (chatMainRef.value) {
      chatMainRef.value.scrollTop = chatMainRef.value.scrollHeight
    }
  })
}

// 调整输入框高度
const adjustTextareaHeight = () => {
  const textarea = textareaRef.value
  if (!textarea) return
  
  textarea.style.height = 'auto'
  const newHeight = Math.min(textarea.scrollHeight, 200)
  textarea.style.height = newHeight + 'px'
}

// 发送消息
const handleSend = async () => {
  if (!inputValue.value.trim() && attachments.value.length === 0) return
  if (!chatStore.currentConversationId) {
    ElMessage.warning('请先创建或选择对话')
    return
  }

  const content = inputValue.value.trim()
  const currentAttachments = [...attachments.value]
  
  // 清空输入
  inputValue.value = ''
  attachments.value = []
  
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }

  isSending.value = true
  isAITyping.value = true
  currentAIMessage.value = ''
  
  try {
    // 发送用户消息
    await chatStore.sendUserMessage(content, currentAttachments)
    scrollToBottom()
    
    // 调用流式 API
    const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
    const token = localStorage.getItem('chat_token')
    
    const response = await fetch(`${baseURL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        conversation_id: chatStore.currentConversationId,
        content: content,
        mode: chatMode.value,
        attachments: currentAttachments.map(att => ({
          filename: att.filename,
          original_filename: att.original_filename,
          file_size: att.file_size,
          mime_type: att.mime_type,
          file_path: att.file_path
        }))
      })
    })

    if (!response.ok) {
      throw new Error('请求失败')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            
            if (data.type === 'token') {
              currentAIMessage.value += data.content
              scrollToBottom()
            } else if (data.type === 'done') {
              isAITyping.value = false
              // 刷新消息列表
              await chatStore.fetchMessages(chatStore.currentConversationId)
              scrollToBottom()
            } else if (data.type === 'error') {
              ElMessage.error(data.content)
              isAITyping.value = false
            }
          } catch (e) {
            console.error('解析SSE消息失败:', e)
          }
        }
      }
    }
    
  } catch (error) {
    console.error('发送消息失败:', error)
    ElMessage.error('发送失败，请重试')
    // 恢复输入内容
    inputValue.value = content
    attachments.value = currentAttachments
    isAITyping.value = false
  } finally {
    isSending.value = false
  }
}

// 处理键盘事件
const handleKeyDown = (e) => {
  if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

// 处理文件选择
const handleFileChange = async (file) => {
  try {
    const uploadedFile = await uploadFile(file.raw)
    
    attachments.value.push({
      id: Date.now() + Math.random(),
      filename: uploadedFile.filename,
      original_filename: uploadedFile.original_filename,
      file_size: uploadedFile.file_size,
      mime_type: uploadedFile.mime_type,
      file_path: uploadedFile.file_path
    })
    
    // 如果添加了附件，自动切换到附件模式
    if (chatMode.value === 'normal') {
      chatMode.value = 'attachment'
    }
    
    ElMessage.success('文件上传成功')
  } catch (error) {
    console.error('文件上传失败:', error)
    ElMessage.error('文件上传失败')
  }
}

// 移除附件
const removeAttachment = (id) => {
  attachments.value = attachments.value.filter(att => att.id !== id)
  // 如果没有附件了，切回普通模式
  if (attachments.value.length === 0 && chatMode.value === 'attachment') {
    chatMode.value = 'normal'
  }
}

// 格式化文件大小
const formatFileSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// 获取当前对话标题
const getCurrentChatTitle = () => {
  const chat = chatStore.conversations.find(c => c.id === chatStore.currentConversationId)
  return chat ? chat.title : '新对话'
}
</script>

<style scoped>
/* 样式保持不变 */
.chat-container {
  height: 100vh;
  display: flex;
  background-color: #f5f5f5;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 24px;
  background: white;
  border-bottom: 1px solid #e0e0e0;
}

.chat-mode-selector {
  margin-left: auto;
}

.message-text {
  line-height: 1.6;
}

.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3) {
  margin-top: 16px;
  margin-bottom: 8px;
}

.message-text :deep(ul),
.message-text :deep(ol) {
  margin-left: 20px;
  margin-bottom: 8px;
}

.message-text :deep(code) {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}

.message-text :deep(pre) {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
}

.typing-indicator {
  display: inline-flex;
  gap: 4px;
  margin-top: 8px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: #909399;
  animation: typing 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    opacity: 0.3;
    transform: translateY(0);
  }
  30% {
    opacity: 1;
    transform: translateY(-8px);
  }
}
</style>