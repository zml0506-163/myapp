<template>
  <div class="chat-container">
    <!-- 侧边栏 -->
    <div :class="['sidebar', { collapsed: !sidebarOpen }]">
      <!-- 侧边栏头部 -->
      <div class="sidebar-header">
        <div class="sidebar-title" @click="sidebarOpen = !sidebarOpen">
          <el-icon :size="20">
            <Fold v-if="sidebarOpen" />
            <Expand v-else />
          </el-icon>
          <span v-if="sidebarOpen">PubMed & 多来源检索</span>
        </div>
        <el-button 
          v-if="sidebarOpen" 
          type="primary" 
          class="new-chat-btn" 
          @click="handleCreateNewChat"
          :loading="chatStore.loading"
        >
          <el-icon style="margin-right: 8px"><Plus /></el-icon>
          新建对话
        </el-button>
        <el-button 
          v-else 
          type="primary" 
          class="new-chat-icon-btn" 
          circle
          @click="handleCreateNewChat"
          :loading="chatStore.loading"
          title="新建对话"
        >
          <el-icon><Plus /></el-icon>
        </el-button>
      </div>

      <!-- 对话历史列表 -->
      <div class="chat-history" v-loading="chatStore.loading && !chatStore.conversations.length">
        <div
          v-for="chat in chatStore.conversations"
          :key="chat.id"
          :class="['chat-item', { active: chatStore.currentConversationId === chat.id }]"
          @click="handleSwitchChat(chat.id)"
        >
          <div class="chat-item-content">
            <el-icon class="chat-item-icon" :size="18"><ChatDotRound /></el-icon>
            <div v-if="sidebarOpen" class="chat-item-text">
              <div class="chat-item-title">{{ chat.title }}</div>
              <div class="chat-item-time">
                <el-icon :size="12"><Clock /></el-icon>
                {{ formatTime(chat.updated_at || chat.created_at) }}
              </div>
            </div>
          </div>
          
          <div v-if="sidebarOpen" class="chat-item-actions" @click.stop>
            <el-dropdown @command="(cmd) => handleChatAction(cmd, chat.id, chat.title)" trigger="click">
              <button class="chat-item-action-btn" title="更多">
                <el-icon :size="14"><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">
                    <el-icon><Edit /></el-icon>
                    <span style="margin-left: 8px">重命名</span>
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" :disabled="chatStore.conversations.length === 1">
                    <el-icon><Delete /></el-icon>
                    <span style="margin-left: 8px">删除</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        
        <!-- 空状态 -->
        <el-empty 
          v-if="!chatStore.loading && !chatStore.conversations.length" 
          description="暂无对话，点击上方按钮创建新对话"
          :image-size="100"
        />
      </div>

      <!-- 侧边栏底部用户信息 -->
      <div class="sidebar-footer">
        <el-dropdown @command="handleUserAction" trigger="click">
          <div class="user-info">
            <div class="user-avatar">
              <el-icon :size="20" style="display: block;"><User /></el-icon>
            </div>
            <span v-if="sidebarOpen" class="user-name">{{ userStore.userInfo?.username || '用户' }}</span>
            <el-icon v-if="sidebarOpen" :size="14"><ArrowUp /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>
                <div style="padding: 4px 0; color: #909399; font-size: 12px;">
                  {{ userStore.userInfo?.email }}
                </div>
              </el-dropdown-item>
              <el-dropdown-item command="logout" divided>
                <el-icon><SwitchButton /></el-icon>
                <span style="margin-left: 8px">退出登录</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 主聊天区域 -->
    <div class="main-content">
      <!-- 头部 -->
      <div class="chat-header">
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
          <!-- 历史消息列表 -->
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
                    {{ att.original_filename }} ({{ formatFileSize(att.file_size) }})
                  </el-tag>
                </div>
              </div>
            </div>
          </div>
          
          <!-- AI 正在生成的消息 -->
          <div v-if="isAITyping" class="message-item assistant-message">
            <div class="avatar assistant-avatar">
              <el-icon :size="20"><ChatDotRound /></el-icon>
            </div>
            <div class="message-content">
              <div class="message-bubble assistant-bubble">
                <!-- 渲染工作流区块 -->
                <div v-for="(section, idx) in workflowSections" :key="idx" class="workflow-section">
                  <!-- 区块标题 -->
                  <div class="section-header" @click="section.collapsed = !section.collapsed">
                    <el-icon :class="['collapse-icon', { collapsed: section.collapsed }]">
                      <ArrowRight />
                    </el-icon>
                    <span class="section-title">{{ section.title }}</span>
                    <span v-if="section.summary" class="section-summary">{{ section.summary }}</span>
                  </div>
                  
                  <!-- 区块内容 -->
                  <div v-show="!section.collapsed" class="section-content">
                    <!-- 日志（可折叠） -->
                    <div v-if="section.logs.length > 0" class="logs-container">
                      <div
                        v-for="(log, logIdx) in section.logs"
                        :key="logIdx"
                        :class="['log-item', `log-source-${log.source || 'default'}`]"
                      >
                        <span v-html="log.content"></span>
                      </div>
                    </div>
                    
                    <!-- 结果（始终显示） -->
                    <div v-if="section.results.length > 0" class="results-container">
                      <div
                        v-for="(result, resultIdx) in section.results"
                        :key="resultIdx"
                        class="result-item"
                        v-html="renderMarkdown(result.content)"
                      ></div>
                    </div>
                  </div>
                </div>
                
                <!-- 正在输入指示器 -->
                <div v-if="!workflowDone" class="typing-indicator">
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

    <!-- 重命名对话框 -->
    <el-dialog v-model="renameDialogVisible" title="重命名对话" width="400px">
      <el-input v-model="renameValue" placeholder="请输入新的对话标题" @keyup.enter="confirmRename" />
      <template #footer>
        <el-button @click="renameDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmRename" :loading="isRenaming">确定</el-button>
      </template>
    </el-dialog>
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
  ArrowRight,
  Plus,
  Clock,
  Edit,
  Delete,
  Expand,
  Fold,
  MoreFilled,
  Setting,
  SwitchButton,
  ArrowUp
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
const uploadRef = ref(null)
const textareaRef = ref(null)
const renameDialogVisible = ref(false)
const renameValue = ref('')
const renamingChatId = ref(null)
const isRenaming = ref(false)
const isSending = ref(false)
const isAITyping = ref(false)
const chatMode = ref('normal')
const workflowDone = ref(false)

// 工作流区块数据结构
const workflowSections = ref([])

// 初始化
onMounted(async () => {
  try {
    // 获取用户信息
    if (!userStore.userInfo) {
      await userStore.getUserInfo()
    }
    
    // 获取对话列表
    await chatStore.fetchConversations()
    
    // 如果有对话，自动选择第一个
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

// 创建新对话
const handleCreateNewChat = async () => {
  try {
    await chatStore.createNewConversation('新对话')
    inputValue.value = ''
    attachments.value = []
  } catch (error) {
    console.error('创建对话失败:', error)
  }
}

// 切换对话
const handleSwitchChat = async (chatId) => {
  if (isSending.value) {
    ElMessage.warning('请等待当前消息发送完成')
    return
  }
  
  try {
    await chatStore.switchConversation(chatId)
    inputValue.value = ''
    attachments.value = []
    scrollToBottom()
  } catch (error) {
    console.error('切换对话失败:', error)
  }
}

// 对话操作
const handleChatAction = (command, chatId, currentTitle) => {
  if (command === 'rename') {
    renamingChatId.value = chatId
    renameValue.value = currentTitle
    renameDialogVisible.value = true
  } else if (command === 'delete') {
    ElMessageBox.confirm('确定要删除这个对话吗？删除后无法恢复。', '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
      confirmButtonClass: 'el-button--danger'
    }).then(async () => {
      try {
        await chatStore.removeConversation(chatId)
      } catch (error) {
        console.error('删除对话失败:', error)
      }
    }).catch(() => {})
  }
}

// 确认重命名
const confirmRename = async () => {
  if (!renameValue.value.trim()) {
    ElMessage.warning('对话标题不能为空')
    return
  }
  
  isRenaming.value = true
  try {
    await chatStore.renameConversation(renamingChatId.value, renameValue.value)
    renameDialogVisible.value = false
    renamingChatId.value = null
    renameValue.value = ''
  } catch (error) {
    console.error('重命名失败:', error)
  } finally {
    isRenaming.value = false
  }
}

// 用户操作
const handleUserAction = async (command) => {
  if (command === 'logout') {
    ElMessageBox.confirm('确定要退出登录吗？', '确认退出', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning'
    }).then(async () => {
      await userStore.logoutAction()
      router.push('/login')
    }).catch(() => {})
  }
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
  workflowDone.value = false
  workflowSections.value = []  // 清空工作流区块
  
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
    
    let currentSection = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            
            if (data.type === 'section_start') {
              // 开始新区块
              currentSection = {
                step: data.step,
                title: data.title,
                collapsible: data.collapsible !== false,
                collapsed: false,  // 初始展开
                logs: [],
                results: [],
                summary: ''
              }
              workflowSections.value.push(currentSection)
              
            } else if (data.type === 'section_end') {
              // 区块结束，折叠日志
              if (currentSection && currentSection.collapsible) {
                currentSection.collapsed = true
              }
              currentSection = null
              
            } else if (data.type === 'log') {
              // 日志消息
              if (currentSection) {
                currentSection.logs.push({
                  content: data.content,
                  source: data.source
                })
              }
              
            } else if (data.type === 'result') {
              // 结果消息
              if (currentSection) {
                if (data.content) {
                  currentSection.results.push({
                    content: data.content,
                    data: data.data
                  })
                }
                if (data.summary) {
                  currentSection.summary = data.summary
                }
              }
              
            } else if (data.type === 'token') {
              // 普通模式的流式token
              if (workflowSections.value.length === 0) {
                // 如果不是工作流模式，创建一个默认区块
                if (!currentSection) {
                  currentSection = {
                    step: 'chat',
                    title: 'AI 回复',
                    collapsible: false,
                    collapsed: false,
                    logs: [],
                    results: [{ content: '', data: null }],
                    summary: ''
                  }
                  workflowSections.value.push(currentSection)
                }
                currentSection.results[0].content += data.content
              }
              
            } else if (data.type === 'done') {
              // 完成
              workflowDone.value = true
              isAITyping.value = false
              
              // 刷新消息列表
              await chatStore.fetchMessages(chatStore.currentConversationId)
              scrollToBottom()
              
            } else if (data.type === 'error') {
              ElMessage.error(data.content)
              isAITyping.value = false
              workflowDone.value = true
            }
            
            scrollToBottom()
            
          } catch (e) {
            console.error('解析SSE消息失败:', e, line)
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
    workflowDone.value = true
  } finally {
    isSending.value = false
  }
}

// 处理键盘事件
const handleKeyDown = (e) => {
  if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  } else if (e.key === 'Enter' && e.ctrlKey) {
    const textarea = e.target
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    inputValue.value = inputValue.value.substring(0, start) + '\n' + inputValue.value.substring(end)
    nextTick(() => {
      textarea.selectionStart = textarea.selectionEnd = start + 1
      adjustTextareaHeight()
    })
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
// 格式化时间
const formatTime = (timestamp) => {
  if (!timestamp) return ''
  
  const now = new Date()
  const time = new Date(timestamp)
  const diff = now - time
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`
  return time.toLocaleDateString('zh-CN')
}
</script>

<style scoped>
/* 基础样式 */
.chat-container {
  height: 100vh;
  display: flex;
  background-color: #f5f5f5;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.sidebar {
  width: 280px;
  background-color: #1a1a1a;
  color: white;
  display: flex;
  flex-direction: column;
  transition: width 0.3s ease;
  border-right: 1px solid #2a2a2a;
  flex-shrink: 0;
}

.sidebar.collapsed {
  width: 68px;
}

.sidebar-header {
  padding: 16px 12px;
  border-bottom: 1px solid #2a2a2a;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  cursor: pointer;
  padding: 4px;
  border-radius: 6px;
  transition: background-color 0.2s;
}

.sidebar-title:hover {
  background-color: #2a2a2a;
}

.sidebar.collapsed .sidebar-title {
  justify-content: center;
}

.sidebar.collapsed .sidebar-title span {
  display: none;
}

.new-chat-btn {
  width: 100%;
}

.new-chat-icon-btn {
  width: auto;
}

.sidebar.collapsed .sidebar-header {
  align-items: center;
}

.chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.chat-history::-webkit-scrollbar {
  width: 6px;
}

.chat-history::-webkit-scrollbar-thumb {
  background-color: #444;
  border-radius: 3px;
}

.chat-item {
  padding: 10px 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
  margin-bottom: 4px;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.chat-item:hover {
  background-color: #2a2a2a;
}

.chat-item.active {
  background-color: #2a2a2a;
}

.chat-item-content {
  display: flex;
  align-items: start;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.sidebar.collapsed .chat-item {
  justify-content: center;
}

.sidebar.collapsed .chat-item-content {
  justify-content: center;
}

.chat-item-icon {
  color: #888;
  flex-shrink: 0;
  margin-top: 2px;
}

.chat-item-text {
  flex: 1;
  min-width: 0;
}

.sidebar.collapsed .chat-item-text {
  display: none;
}

.chat-item-title {
  font-size: 14px;
  color: #e0e0e0;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-item-time {
  font-size: 12px;
  color: #888;
  display: flex;
  align-items: center;
  gap: 4px;
}

.chat-item-actions {
  opacity: 0;
  transition: opacity 0.2s;
  flex-shrink: 0;
}

.chat-item:hover .chat-item-actions {
  opacity: 1;
}

.sidebar.collapsed .chat-item-actions {
  display: none;
}

.chat-item-action-btn {
  padding: 4px 6px;
  border-radius: 4px;
  background: transparent;
  border: none;
  color: #888;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
}

.chat-item-action-btn:hover {
  background-color: #3a3a3a;
  color: #fff;
}

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid #2a2a2a;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.user-info:hover {
  background-color: #2a2a2a;
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: #409eff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: white;
}

.user-name {
  flex: 1;
  font-size: 14px;
  color: #e0e0e0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sidebar.collapsed .user-name,
.sidebar.collapsed .user-info .el-icon:last-child {
  display: none;
}

.sidebar.collapsed .user-info {
  justify-content: center;
  padding: 8px 4px;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f5f5;
  min-width: 0;
}


.toggle-sidebar-btn {
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
  display: flex;
  align-items: center;
}

.toggle-sidebar-btn:hover {
  background-color: #f0f0f0;
}


.chat-main {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
}

.chat-main::-webkit-scrollbar {
  width: 8px;
}

.chat-main::-webkit-scrollbar-thumb {
  background-color: #ccc;
  border-radius: 4px;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.messages-wrapper {
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}

.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}

.user-message {
  flex-direction: row-reverse;
}

.assistant-message {
  flex-direction: row;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: white;
}

.user-avatar {
  background-color: #409eff;
}

.assistant-avatar {
  background-color: #9b59b6;
}

.message-content {
  flex: 1;
  max-width: 80%;
}

.user-message .message-content {
  text-align: right;
}

.assistant-message .message-content {
  text-align: left;
}

.message-bubble {
  display: inline-block;
  padding: 12px 16px;
  border-radius: 16px;
  word-wrap: break-word;
}

.user-bubble {
  background-color: #409eff;
  color: white;
}

.assistant-bubble {
  background-color: white;
  color: #303133;
  border: 1px solid #e0e0e0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.message-text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.6;
}

.message-attachments {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}


.chat-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 24px;
  background: white;
  border-bottom: 1px solid #e0e0e0;
}

.chat-header h1 {
  flex: 1;
  margin: 0;
  font-size: 18px;
}

/* 工作流区块样式 */
.workflow-section {
  margin: 16px 0;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  overflow: hidden;
  background: white;
}

.section-header {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  background: #f5f7fa;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.section-header:hover {
  background: #e8ebf0;
}

.collapse-icon {
  transition: transform 0.2s;
  margin-right: 8px;
}

.collapse-icon.collapsed {
  transform: rotate(0deg);
}

.collapse-icon:not(.collapsed) {
  transform: rotate(90deg);
}

.section-title {
  font-weight: 600;
  color: #303133;
  margin-right: 12px;
}

.section-summary {
  color: #67c23a;
  font-size: 14px;
}

.section-content {
  padding: 16px;
}

/* 日志样式 */
.logs-container {
  margin-bottom: 12px;
  padding: 12px;
  background: #f9fafb;
  border-radius: 6px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  max-height: 300px;
  overflow-y: auto;
}

.log-item {
  color: #606266;
  line-height: 1.6;
}

.log-source-pubmed {
  color: #409eff;
}

.log-source-europepmc {
  color: #67c23a;
}

.log-source-clinical_trials {
  color: #e6a23c;
}

/* 结果样式 */
.results-container {
  line-height: 1.8;
}

.result-item {
  margin-bottom: 12px;
}

/* 正在输入指示器 */
.typing-indicator {
  display: inline-flex;
  gap: 4px;
  margin-top: 12px;
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

/* 其他样式保持不变 */
.message-text :deep(h1),
.message-text :deep(h2),
.message-text :deep(h3) {
  margin-top: 16px;
  margin-bottom: 8px;
}

.message-text :deep(code) {
  background: #f5f5f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
}


.chat-footer {
  background-color: white;
  border-top: 1px solid #e0e0e0;
  padding: 16px;
}

.input-wrapper {
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}

.attachments-preview {
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.input-area {
  display: flex;
  gap: 8px;
}

.textarea-wrapper {
  flex: 1;
  border: 1px solid #dcdfe6;
  border-radius: 12px;
  background-color: white;
  transition: border-color 0.2s;
}

.textarea-wrapper:focus-within {
  border-color: #409eff;
}

.custom-textarea {
  width: 98%;
  border: none;
  outline: none;
  resize: none;
  font-size: 14px;
  line-height: 1.5;
  margin: 10px;
  font-family: inherit;
  min-height: 24px;
  max-height: 200px;
  overflow-y: auto;
}

.custom-textarea::-webkit-scrollbar {
  width: 6px;
}

.custom-textarea::-webkit-scrollbar-thumb {
  background-color: #ddd;
  border-radius: 3px;
}

.custom-textarea:disabled {
  background-color: #f5f7fa;
  cursor: not-allowed;
}

.textarea-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px 8px;
}

.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.send-btn {
  border-radius: 8px;
}

.input-hint {
  margin: 8px 0 0 0;
  text-align: center;
  font-size: 12px;
  color: #909399;
}

:deep(.el-dropdown-menu__item) {
  display: flex;
  align-items: center;
  gap: 4px;
}

:deep(.el-loading-mask) {
  background-color: rgba(255, 255, 255, 0.7);
}
</style>