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
        <div class="toggle-sidebar-btn" @click="sidebarOpen = !sidebarOpen">
          <el-icon :size="12"><Clock /></el-icon>
        </div>
        <h1>{{ getCurrentChatTitle() }}</h1>
      </div>

      <!-- 消息区域 -->
      <div class="chat-main" ref="chatMainRef" v-loading="chatStore.loading && !chatStore.messages.length">
        <!-- 空状态 -->
        <div v-if="!chatStore.currentConversationId" class="empty-state">
          <el-empty description="请选择或创建一个对话开始聊天" :image-size="200" />
        </div>
        
        <!-- 消息列表 -->
        <div v-else class="messages-wrapper">
          <div
            v-for="message in chatStore.messages"
            :key="message.id"
            :class="['message-item', message.message_type === 'user' ? 'user-message' : 'assistant-message']"
          >
            <!-- 头像 -->
            <div :class="['avatar', message.message_type === 'user' ? 'user-avatar' : 'assistant-avatar']">
              <el-icon :size="20">
                <User v-if="message.message_type === 'user'" />
                <ChatDotRound v-else />
              </el-icon>
            </div>

            <!-- 消息内容 -->
            <div class="message-content">
              <div :class="['message-bubble', message.message_type === 'user' ? 'user-bubble' : 'assistant-bubble']">
                <p class="message-text">{{ message.content }}</p>
                
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
          
          <!-- AI 正在输入提示 -->
          <div v-if="isAITyping" class="message-item assistant-message">
            <div class="avatar assistant-avatar">
              <el-icon :size="20"><ChatDotRound /></el-icon>
            </div>
            <div class="message-content">
              <div class="message-bubble assistant-bubble">
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

          <!-- 输入框区域 -->
          <div class="input-area">
            <!-- 输入框 -->
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
              
              <!-- 底部工具栏 -->
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

          <p class="input-hint">按 Enter 发送，Ctrl + Enter 换行</p>
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
import {
  User,
  ChatDotRound,
  Paperclip,
  Promotion,
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

// 获取当前对话标题
const getCurrentChatTitle = () => {
  const chat = chatStore.conversations.find(c => c.id === chatStore.currentConversationId)
  return chat ? chat.title : '新对话'
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
  
  try {
    // 发送用户消息
    await chatStore.sendUserMessage(content, currentAttachments)
    scrollToBottom()
    
    // 模拟 AI 回复
    isAITyping.value = true
    
    // 这里应该调用真实的 AI API
    // 暂时使用模拟回复
    setTimeout(async () => {
      const aiResponse = `收到您的消息："${content}"。这是一个模拟的 AI 回复，实际应用中这里会调用大语言模型 API。`
      chatStore.receiveAIMessage(aiResponse)
      isAITyping.value = false
      scrollToBottom()
    }, 1500)
    
  } catch (error) {
    console.error('发送消息失败:', error)
    // 恢复输入内容
    inputValue.value = content
    attachments.value = currentAttachments
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
    // 上传文件
    const uploadedFile = await uploadFile(file.raw, (percent) => {
      console.log('上传进度:', percent)
    })
    
    // 添加到附件列表
    attachments.value.push({
      id: Date.now() + Math.random(),
      filename: uploadedFile.filename,
      original_filename: uploadedFile.original_filename,
      file_size: uploadedFile.file_size,
      mime_type: uploadedFile.mime_type
    })
    
    ElMessage.success('文件上传成功')
  } catch (error) {
    console.error('文件上传失败:', error)
    ElMessage.error('文件上传失败')
  }
}

// 移除附件
const removeAttachment = (id) => {
  attachments.value = attachments.value.filter(att => att.id !== id)
}

// 格式化文件大小
const formatFileSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
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
.chat-container {
  height: 100vh;
  display: flex;
  background-color: #f5f5f5;
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

.chat-header {
  background-color: white;
  border-bottom: 1px solid #e0e0e0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
  display: flex;
  align-items: center;
  padding: 16px 24px;
  gap: 12px;
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

.chat-header h1 {
  font-size: 18px;
  font-weight: 600;
  color: #303133;
  margin: 0;
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

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0;
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