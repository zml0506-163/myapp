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
          <span v-if="sidebarOpen">对话列表</span>
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
        
        <el-empty 
          v-if="!chatStore.loading && !chatStore.conversations.length" 
          description="暂无对话"
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
        
        <!-- 多源检索开关 -->
        <div class="multi-source-toggle">
          <el-checkbox v-model="enableMultiSource" label="多源检索" size="large" />
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
              <!-- 用户消息：保留换行 -->
              <div v-if="message.message_type === 'user'" class="message-bubble user-bubble">
                <div class="message-text user-text">{{ message.content }}</div>
                
                <!-- 附件显示 -->
                <div v-if="message.attachments && message.attachments.length > 0" class="message-attachments">
                  <el-tag
                    v-for="att in message.attachments"
                    :key="att.id"
                    type="info"
                    size="small"
                  >
                    <el-icon style="margin-right: 4px"><Paperclip /></el-icon>
                    {{ att.original_filename }}
                  </el-tag>
                </div>
              </div>
              
              <!-- AI消息：渲染Markdown -->
              <div v-else class="message-bubble assistant-bubble">
                <div class="message-text assistant-text" v-html="renderMarkdown(message.content)"></div>
                
                <!-- 附件显示 -->
                <div v-if="message.attachments && message.attachments.length > 0" class="message-attachments">
                  <el-tag
                    v-for="att in message.attachments"
                    :key="att.id"
                    type="success"
                    size="small"
                  >
                    <el-icon style="margin-right: 4px"><Paperclip /></el-icon>
                    {{ att.original_filename }}
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
                <!-- ========== 工作流模式：显示区块 ========== -->
                <div v-if="isWorkflowMode && workflowSections.length > 0">
                  <div v-for="(section, idx) in workflowSections" :key="`section-${section.step}-${idx}`" class="workflow-section">
                    <!-- 区块标题 -->
                    <div class="section-header" @click="toggleSection(idx)">
                      <el-icon :class="['collapse-icon', { collapsed: section.collapsed }]">
                        <ArrowRight />
                      </el-icon>
                      <span class="section-title">{{ section.title }}</span>
                      <span v-if="section.summary" class="section-summary">{{ section.summary }}</span>
                    </div>
                    
                    <!-- 区块内容 -->
                    <div v-show="!section.collapsed" class="section-content">
                      <!-- 日志 -->
                      <div v-if="section.logs && section.logs.length > 0" class="logs-container">
                        <span
                          v-for="(log, logIdx) in section.logs"
                          :key="`log-${idx}-${logIdx}`"
                          :class="['log-item', `log-source-${log.source || 'default'}`]"
                          v-html="log.content"
                        ></span>
                      </div>
                      
                      <!-- 结果 -->
                      <div v-if="section.results && section.results.length > 0" class="results-container">
                        <div
                          v-for="(result, resultIdx) in section.results"
                          :key="`result-${idx}-${resultIdx}`"
                          class="result-item assistant-text"
                          v-html="renderMarkdown(result.content)"
                        ></div>
                      </div>
                    </div>
                  </div>
                </div>
                
                <!-- ========== 普通模式：直接显示文本 ========== -->
                <div v-else-if="!isWorkflowMode && simpleResponse" class="assistant-text" v-html="renderMarkdown(simpleResponse)"></div>
                
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
          <div v-if="conversationAttachments.length > 0" class="attachments-preview">
            <div class="attachments-header">
              <span>当前会话附件：</span>
              <el-button text size="small" @click="clearAllAttachments">清除全部</el-button>
            </div>
            <el-tag
              v-for="att in conversationAttachments"
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
                  <!-- 停止按钮 -->
                  <el-button
                    v-if="isSending"
                    type="danger"
                    text
                    @click="handleStop"
                    class="stop-btn"
                    title="停止生成"
                  >
                    <el-icon><CircleClose /></el-icon>
                  </el-button>
                  
                  <!-- 发送按钮 -->
                  <el-button
                    v-else
                    type="primary"
                    :disabled="!inputValue.trim() || !chatStore.currentConversationId"
                    @click="handleSend"
                    class="send-btn"
                  >
                    <el-icon><Promotion /></el-icon>
                  </el-button>
                </div>
              </div>
            </div>
          </div>

          <p class="input-hint">
            按 Enter 发送，Ctrl + Enter 换行
            <span v-if="conversationAttachments.length > 0"> | 附件模式</span>
            <span v-if="enableMultiSource"> | 多源检索</span>
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
import { ref, nextTick, onMounted, watch } from 'vue'
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
  SwitchButton,
  ArrowUp,
  CircleClose
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { useChatStore } from '@/stores/chat'
import { uploadFile } from '@/api/upload'

const router = useRouter()
const userStore = useUserStore()
const chatStore = useChatStore()

// 状态
const inputValue = ref('')
const conversationAttachments = ref([])
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
const enableMultiSource = ref(false)
const workflowDone = ref(false)
const workflowSections = ref([])  // 改用 ref
const simpleResponse = ref('')  // 用于普通模式的纯文本响应
const isWorkflowMode = ref(false)  //标识当前是否为工作流模式
const currentReader = ref(null)  // 用于存储当前的 Reader，以便停止

// 监听对话切换，清空附件
watch(() => chatStore.currentConversationId, () => {
  conversationAttachments.value = []
})

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
    conversationAttachments.value = []
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
    conversationAttachments.value = []
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

// 切换区块展开/折叠
const toggleSection = (idx) => {
  const section = workflowSections.value[idx]
  if (section.collapsible !== false) {
    section.collapsed = !section.collapsed
  }
}

// 停止生成
const handleStop = async () => {
  try {
    if (currentReader.value) {
      await currentReader.value.cancel()
      currentReader.value = null
    }
    
    isSending.value = false
    isAITyping.value = false
    workflowDone.value = true
    
    ElMessage.info('已停止生成')
  } catch (error) {
    console.error('停止失败:', error)
  }
}

// 发送消息
const handleSend = async () => {
  if (!inputValue.value.trim()) return
  if (!chatStore.currentConversationId) {
    ElMessage.warning('请先创建或选择对话')
    return
  }

  const content = inputValue.value.trim()
  
  // 确定模式
  let mode = 'normal'
  if (enableMultiSource.value) {
    mode = 'multi_source'
  } else if (conversationAttachments.value.length > 0) {
    mode = 'attachment'
  }

  // 清空输入
  inputValue.value = ''
  
  if (textareaRef.value) {
    textareaRef.value.style.height = 'auto'
  }

  isSending.value = true
  isAITyping.value = true
  workflowDone.value = false
  
  // 清空之前的状态
  workflowSections.value = []
  simpleResponse.value = ''
  isWorkflowMode.value = (mode === 'multi_source')
  
  try {
    // 刷新发送消息页面样式
    await chatStore.sendUserMessage(content, conversationAttachments.value)
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
        mode: mode,
        attachments: conversationAttachments.value
      })
    })

    if (!response.ok) {
      throw new Error('请求失败')
    }

    const reader = response.body.getReader()
    currentReader.value = reader
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
            
            // === 工作流模式的事件处理 ===
            if (data.type === 'section_start') {
              currentSection = {
                step: data.step,
                title: data.title,
                collapsible: data.collapsible !== false,
                collapsed: false,
                logs: [],
                results: [],
                summary: ''
              }
              workflowSections.value = [...workflowSections.value, currentSection]
              
            } else if (data.type === 'section_end') {
              if (currentSection) {
                const idx = workflowSections.value.findIndex(s => s.step === currentSection.step)
                if (idx !== -1) {
                  // 保留所有内容，只修改折叠状态
                  const section = workflowSections.value[idx]

                  // 调试日志
                  console.log(`[DEBUG] Section ${data.step} ending:`, {
                    logs_count: section.logs.length,
                    results_count: section.results.length,
                    collapsed: section.collapsed
                  })

                  workflowSections.value[idx] = {
                    ...section,
                    collapsed: section.collapsible !== false ? true : false
                  }
                }
              }
              currentSection = null
              
            } else if (data.type === 'log') {
              // 查找当前活跃区块
              let targetSection = currentSection
              
              // 如果没有当前区块，尝试根据 step 查找
              if (!targetSection && data.step) {
                const sectionIdx = workflowSections.value.findIndex(s => s.step === data.step)
                if (sectionIdx !== -1) {
                  targetSection = workflowSections.value[sectionIdx]
                }
              }
              
              if (targetSection) {
                const sectionIdx = workflowSections.value.findIndex(s => s.step === targetSection.step)
                if (sectionIdx !== -1) {
                  const section = workflowSections.value[sectionIdx]
                  
                  if (data.newline === false && section.logs.length > 0) {
                    // 追加到最后一条日志
                    const lastIdx = section.logs.length - 1
                    const updatedLogs = [...section.logs]
                    updatedLogs[lastIdx] = {
                      ...updatedLogs[lastIdx],
                      content: updatedLogs[lastIdx].content + data.content
                    }
                    workflowSections.value[sectionIdx] = {
                      ...section,
                      logs: updatedLogs
                    }
                  } else {
                    // 新建日志
                    workflowSections.value[sectionIdx] = {
                      ...section,
                      logs: [...section.logs, {
                        content: data.content,
                        source: data.source
                      }]
                    }
                  }
                }
              }
            } else if (data.type === 'result') {
              // 查找目标区块
              let targetSection = currentSection
              
              if (!targetSection && data.step) {
                const sectionIdx = workflowSections.value.findIndex(s => s.step === data.step)
                if (sectionIdx !== -1) {
                  targetSection = workflowSections.value[sectionIdx]
                }
              }
              
              if (targetSection) {
                const sectionIdx = workflowSections.value.findIndex(s => s.step === targetSection.step)
                if (sectionIdx !== -1) {
                  const section = workflowSections.value[sectionIdx]
                  
                  const updates = {}
                  if (data.content) {
                    updates.results = [...section.results, {
                      content: data.content,
                      data: data.data
                    }]
                  }
                  if (data.summary) {
                    updates.summary = data.summary
                  }
                  
                  workflowSections.value[sectionIdx] = {
                    ...section,
                    ...updates
                  }
                }
              }
            } else if (data.type === 'token') {
              // === 普通模式：逐字追加 ===
              if (isWorkflowMode.value) {
                // 工作流模式中的 token（最终报告）
                if (!currentSection) {
                  currentSection = {
                    step: 'final_report',
                    title: '📝 最终报告',
                    collapsible: false,
                    collapsed: false,
                    logs: [],
                    results: [{ content: '', data: null }],
                    summary: ''
                  }
                  workflowSections.value = [...workflowSections.value, currentSection]
                }
                
                const sectionIdx = workflowSections.value.findIndex(s => s.step === currentSection.step)
                if (sectionIdx !== -1 && workflowSections.value[sectionIdx].results.length > 0) {
                  const section = workflowSections.value[sectionIdx]
                  const updatedResults = [...section.results]
                  updatedResults[0] = {
                    ...updatedResults[0],
                    content: updatedResults[0].content + data.content
                  }
                  workflowSections.value[sectionIdx] = {
                    ...section,
                    results: updatedResults
                  }
                }
              } else {
                // 纯普通模式：直接追加到 simpleResponse
                simpleResponse.value += data.content
              }
              
            } else if (data.type === 'done') {
              workflowDone.value = true
              isAITyping.value = false
              currentReader.value = null
              await chatStore.fetchMessages(chatStore.currentConversationId)
              
            } else if (data.type === 'title_updated') {
              const conversationId = data.conversation_id
              const newTitle = data.title
              
              const conv = chatStore.conversations.find(c => c.id === conversationId)
              if (conv) {
                conv.title = newTitle
              }
              
              ElMessage.success(`对话已自动重命名为「${newTitle}」`)
              
            } else if (data.type === 'error') {
              ElMessage.error(data.content)
              isAITyping.value = false
              workflowDone.value = true
              currentReader.value = null
            }
            
            await nextTick()
            scrollToBottom()
            
          } catch (e) {
            console.error('解析SSE消息失败:', e, line)
          }
        }
      }
    }
    
    currentReader.value = null
    
  } catch (error) {
    console.error('发送消息失败:', error)
    ElMessage.error('发送失败，请重试')
    inputValue.value = content
    isAITyping.value = false
    workflowDone.value = true
    currentReader.value = null
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
    
    conversationAttachments.value.push({
      id: Date.now() + Math.random(),
      filename: uploadedFile.filename,
      original_filename: uploadedFile.original_filename,
      file_size: uploadedFile.file_size,
      mime_type: uploadedFile.mime_type,
      file_path: uploadedFile.file_path
    })
    
    ElMessage.success('文件上传成功')
  } catch (error) {
    console.error('文件上传失败:', error)
    ElMessage.error('文件上传失败')
  }
}

// 移除附件
const removeAttachment = (id) => {
  conversationAttachments.value = conversationAttachments.value.filter(att => att.id !== id)
}

// 清除全部附件
const clearAllAttachments = () => {
  conversationAttachments.value = []
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
/* ============================================
   基础容器样式
   ============================================ */
.chat-container {
  height: 100vh;
  display: flex;
  background-color: #f5f5f5;
  font-size: 14px;
}

/* ============================================
   侧边栏样式
   ============================================ */
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
  text-align: left;
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

/* ============================================
   主内容区域
   ============================================ */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  background-color: #f5f5f5;
  min-width: 0;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: white;
  border-bottom: 1px solid #e0e0e0;
}

.chat-header h1 {
  margin: 0;
  font-size: 18px;
  text-align: left;
}

.multi-source-toggle {
  display: flex;
  align-items: center;
}

.chat-main {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
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

/* ============================================
   消息气泡样式
   ============================================ */
.message-item {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}

.user-message {
  flex-direction: row-reverse;
}

.assistant-message {
  flex-direction: row;
}

.avatar {
  width: 32px;
  height: 32px;
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
  padding: 10px 14px;
  border-radius: 10px;
  word-wrap: break-word;
  text-align: left;
  font-size: 14px;
  line-height: 1.5;
}

.user-bubble {
  background-color: #409eff;
  color: white;
}

.assistant-bubble {
  background-color: white;
  color: #303133;
  border: 1px solid #e4e7ed;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.user-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant-text {
  white-space: normal;
  word-break: break-word;
}

.message-attachments {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* ============================================
  Markdown 内容样式
============================================ */
.assistant-text :deep(h1) {
  margin-top: 12px;
  margin-bottom: 8px;
  font-weight: 600;
  line-height: 1.3;
  font-size: 1.5em;  /* 添加这行，原来默认是3.2em */
}

.assistant-text :deep(h2) {
  margin-top: 10px;
  margin-bottom: 6px;
  font-weight: 600;
  line-height: 1.3;
  font-size: 1.3em;  /* 添加这行 */
}

.assistant-text :deep(h3) {
  margin-top: 10px;
  margin-bottom: 6px;
  font-weight: 600;
  line-height: 1.3;
  font-size: 1.1em;  /* 添加这行 */
}

.assistant-text :deep(h4) {
  margin-top: 10px;
  margin-bottom: 6px;
  font-weight: 600;
  line-height: 1.3;
  font-size: 1em;  /* 添加这行 */
}

.assistant-text :deep(p) {
  margin: 5px 0;
  line-height: 1.6;
}

.assistant-text :deep(ul),
.assistant-text :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}

.assistant-text :deep(code) {
  background: #f5f5f5;
  padding: 2px 5px;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 0.9em;
  color: #e6426a;
}

.assistant-text :deep(pre) {
  background: #f5f5f5;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
  margin: 8px 0;
}

.assistant-text :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 0.9em;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.assistant-text :deep(table th) {
  background: #f5f7fa;
  color: #606266;
  font-weight: 600;
  padding: 6px 8px;
  text-align: left;
  border: 1px solid #e4e7ed;
}

.assistant-text :deep(table td) {
  padding: 6px 8px;
  border: 1px solid #e4e7ed;
  color: #303133;
}

/* ============================================
   工作流区块样式
   ============================================ */
.workflow-section {
  margin: 8px 0;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
  background: white;
}

.section-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #f5f7fa;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
  font-size: 13px;
}

.section-header:hover {
  background: #ecf0f5;
}

.collapse-icon {
  transition: transform 0.15s;
  margin-right: 6px;
  font-size: 14px;
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
  margin-right: 10px;
  font-size: 13px;
}

.section-summary {
  color: #67c23a;
  font-size: 12px;
}

.section-content {
  padding: 10px 12px;
}

.logs-container {
  margin-bottom: 8px;
  padding: 8px 10px;
  background: #f9fafb;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  max-height: 250px;
  overflow-y: auto;
  line-height: 1.4;
}

.log-item {
  color: #606266;
  display: inline;
  white-space: pre-wrap;
  word-break: break-word;
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

.results-container {
  line-height: 1.5;
}

.result-item {
  margin-bottom: 8px;
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

/* ============================================
   输入区域样式
   ============================================ */
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
  padding: 12px;
  background: #f5f7fa;
  border-radius: 8px;
}

.attachments-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
  color: #606266;
}

.attachments-preview .el-tag {
  margin-right: 8px;
  margin-bottom: 8px;
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
  width: calc(100% - 20px);
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

.send-btn,
.stop-btn {
  border-radius: 8px;
}

.input-hint {
  margin: 8px 0 0 0;
  text-align: center;
  font-size: 12px;
  color: #909399;
}
</style>