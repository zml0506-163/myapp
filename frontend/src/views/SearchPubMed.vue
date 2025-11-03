<template>
    <div class="container">
      <h1>PubMed & 多来源检索</h1>
      <div class="search-container">
        <span class="input-span">关键词：</span>
        <input v-model="q" type="text" placeholder="关键词，如 cancer AND immunotherapy" />
        
        <span class="input-span">检索数量：</span>
        <input v-model.number="limit" type="number" min="1" max="210" class="input-number" />
        
        <!-- 按钮直接绑定click事件，替代form的submit -->
        <button :disabled="loading" @click="run">
          <span v-if="loading">搜索中...</span>
          <span v-else>搜索</span>
        </button>
        <button @click="showPaperDialog = true">查看文献列表</button>
        <button @click="showTrialDialog = true">查看临床试验</button>
      </div>
  
      <div class="output">
        <div 
          v-for="(line, lineIdx) in renderedLines" 
          :key="`line-${lineIdx}`" 
          class="msg"
        >
          <span 
            v-for="(msg, msgIdx) in line" 
            :key="`line-${lineIdx}-msg-${msgIdx}`"
            class="msg-item"
          >
            <span 
              v-if="msg.type === 'text'" 
              class="msg-text" 
              v-html="msg.content"
            ></span>
      
            <a 
              v-else-if="msg.type === 'link'" 
              :href="msg.href" 
              :data-ids="msg.ids"  
              :data-event-type="msg.eventType"
              class="msg-link" 
              @click.prevent="handleLinkClick"
            >{{ msg.content }}</a>
      
            <img 
              v-else-if="msg.type === 'image'" 
              :src="msg.url" 
              class="msg-img" 
              alt=""
            />
      
            <span v-else class="msg-other">
              {{ JSON.stringify(msg) }}
            </span>
          </span>
        </div>
      </div>
      
  
      <!-- 临床试验列表对话框 -->
    <el-dialog v-model="showTrialDialog" title="临床试验列表" width="90%" max-height="90vh">
      <!-- 搜索区域 -->
      <div class="search-container" style="margin-bottom: 15px;">
        <el-row :gutter="10">
          <el-col :span="8">
            <el-input 
              v-model="trialSearchParams.nctId" 
              placeholder="搜索NCT编号,多个逗号分隔" 
              clearable
              @clear="handleTrialSearch"
              @keyup.enter="handleTrialSearch"
            />
          </el-col>
          <el-col :span="6">
            <el-input 
              v-model="trialSearchParams.condition" 
              placeholder="搜索疾病/条件" 
              clearable
              @clear="handleTrialSearch"
              @keyup.enter="handleTrialSearch"
            />
          </el-col>
          <el-col :span="6">
            <el-select 
              v-model="trialSearchParams.status" 
              placeholder="选择状态" 
              clearable
              @change="handleTrialSearch"
            >
              <el-option 
                v-for="status in allStatuses" 
                :key="status.value" 
                :label="status.label" 
                :value="status.value"
              />
            </el-select>
          </el-col>
          <el-col :span="2">
            <el-button type="primary" @click="handleTrialSearch">搜索</el-button>
          </el-col>
          <el-col :span="2">
            <el-button style="margin-left: 10px;"  @click="resetTrialSearch" >重置</el-button>
          </el-col>
        </el-row>
      </div>
  
      <!-- 表格内容 -->
      <el-table
        :data="trialList"
        style="width: 100%"
        border
        v-loading="trialLoading"
        element-loading-text="加载中..."
        height="calc(100% - 60px)"
      >
        <el-table-column prop="nct_id" label="NCT编号" align="center" />
        <el-table-column prop="title" label="标题" min-width="290">
          <template #default="scope">
            <div class="title-cell">
              <span>{{ scope.row.title }}</span>
              <template v-if="scope.row.official_title">
                <div class="official-title">{{ scope.row.official_title }}</div>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态"  align="center">
          <template #default="scope">
            <el-tooltip 
              :content="getStatusDescription(scope.row.status)"
              placement="top"
            >
              <el-tag 
                :type="statusTagType(scope.row.status)"
                :effect="scope.row.status === 'COMPLETED' ? 'dark' : 'light'"
                style="cursor: pointer;"
              >
                {{ formatStatus(scope.row.status) }}
              </el-tag>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column prop="phase" label="临床阶段" align="center" />
        <el-table-column prop="study_type" label="研究类型"  align="center" />
        <el-table-column prop="conditions" label="疾病/条件" />
        <el-table-column prop="start_date" label="开始日期"  align="center" />
        <el-table-column prop="completion_date" label="完成日期" align="center" />
        <el-table-column label="操作" align="center">
          <template #default="scope">
            <el-button 
              type="text" 
              @click="openSourceUrl(scope.row.source_url)"
              :disabled="!scope.row.source_url"
            >
              原始链接
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      
      <!-- 分页组件 -->
      <div class="pagination-container" style="margin-top: 15px; text-align: right;">
        <el-pagination
          v-model:current-page="trialPagination.currentPage"
          v-model:page-size="trialPagination.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="trialPagination.total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handleTrialSizeChange"
          @current-change="handleTrialCurrentChange"
        />
      </div>
  
      <template #footer>
        <el-button @click="showTrialDialog = false">关闭</el-button>
      </template>
    </el-dialog>
  
      <el-dialog v-model="showPaperDialog" title="已存储的文献列表" width="80%">
        <!-- 搜索区域 -->
        <div class="search-container" style="margin-bottom: 15px;">
          <el-row :gutter="10">
            <el-col :span="6">
              <el-input 
                v-model="searchParams.pmid" 
                placeholder="按PMID搜索" 
                clearable
                @clear="handlePaperSearch"
                @keyup.enter="handlePaperSearch"
              />
            </el-col>
            <el-col :span="9">
              <el-input 
                v-model="searchParams.title" 
                placeholder="按标题搜索" 
                clearable
                @clear="handlePaperSearch"
                @keyup.enter="handlePaperSearch"
              />
            </el-col>
            <el-col :span="5">
              <el-input 
                v-model="searchParams.author" 
                placeholder="按作者搜索" 
                clearable
                @clear="handlePaperSearch"
                @keyup.enter="handlePaperSearch"
              />
            </el-col>
            <el-col :span="2">
              <el-button type="primary" @click="handlePaperSearch">搜索</el-button>
            </el-col>
            <el-col :span="2">
              <el-button 
                style="margin-left: 10px;" 
                @click="resetPaperSearch"
              >
                重置
              </el-button>
            </el-col>
          </el-row>
        </div>
      
        <el-table
          :data="paperList"
          style="width: 100%"
          border
          v-loading="paperLoading"
        >
          <el-table-column prop="pmid" label="PMID" width="120" />
          <el-table-column prop="pmcid" label="PMCID" width="150" />
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="pub_date" label="出版时间" width="120" />
          <el-table-column prop="source_type" label="来源" width="120" />
          <el-table-column label="操作" width="240">
            <template #default="scope">
              <el-button type="success" @click="downloadPDF(scope.row.pdf_url)">
                下载 PDF
              </el-button>
              <el-button type="primary" @click="openSourceUrl(scope.row.source_url)">
                原文链接
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      
      <!-- 文献分页组件 -->
      <div class="pagination-container" style="margin-top: 15px; text-align: right;">
        <el-pagination
          v-model:current-page="paperPagination.currentPage"
          v-model:page-size="paperPagination.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="paperPagination.total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="handlePaperSizeChange"
          @current-change="handlePaperCurrentChange"
        />
      </div>
  
      <template #footer>
        <el-button @click="showPaperDialog = false">关闭</el-button>
      </template>
    </el-dialog>
    </div>
  </template>
  
  <script setup>
  import { ref, reactive, watch, computed } from "vue";
  import DOMPurify from 'dompurify';
  import { ElMessage, ElButton, ElDialog, ElTable, ElTableColumn } from 'element-plus';
  import 'element-plus/dist/index.css';
  
  const q = ref("");
  const limit = ref(5);
  
  // 临床试验对话框状态
  const showTrialDialog = ref(false);
  const trialList = ref([]);
  const trialLoading = ref(false);
  const trialPagination = reactive({
    currentPage: 1,
    pageSize: 10,
    total: 0
  });
  
  // 文献对话框状态
  const showPaperDialog = ref(false);
  const paperList = ref([]);
  const paperLoading = ref(false);
  const paperPagination = reactive({
    currentPage: 1,
    pageSize: 10,
    total: 0
  });
  
  const rawMessages = ref([]); // 存储原始SSE消息（替代原messages）
  const loading = ref(false);
  
  const renderedLines = computed(() => {
    const lines = [];
    let currentLine = [];
  
    // 调试：打印原始数组快照（只一次）
    try {
      console.debug('[renderedLines] rawMessages snapshot:', JSON.parse(JSON.stringify(rawMessages.value)));
    } catch (e) {
      console.debug('[renderedLines] rawMessages (no clone):', rawMessages.value);
    }
  
    rawMessages.value.forEach((msg, idx) => {
      const safeMsg = { ...msg };
  
      if (safeMsg.type === 'text') {
        if (safeMsg.content == null) safeMsg.content = '';
        safeMsg.content = DOMPurify.sanitize(String(safeMsg.content));
      }
  
      if (safeMsg.newline) {
        if (currentLine.length > 0) {
          lines.push(currentLine);
        }
        currentLine = [safeMsg];
      } else {
        currentLine.push(safeMsg);
      }
    });
  
    // 尾部收尾
    if (currentLine.length > 0) {
      lines.push(currentLine);
    }
  
    console.debug('[renderedLines] final lines:', lines.map(line => line.map(m => m.content)));
  
    return lines;
  });
  
  
  
  async function run() {
    if(q.value == ''){
      ElMessage.warning('请输入搜索关键词！');
      return
    }
    rawMessages.value = []; // 清空历史消息
    loading.value = true;
  
    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": "Bearer YOUR_TOKEN"
        },
        body: JSON.stringify({ q: q.value, limit: limit.value })
      });
  
      if (!res.ok) throw new Error(`请求失败: ${res.status}`);
  
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
  
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
  
        // 解码SSE流并解析每一行JSON
        const chunk = decoder.decode(value, { stream: true });
        chunk.split("\n").forEach(line => {
          if (!line.trim()) return; // 跳过空行
          try {
            const obj = JSON.parse(line);
            console.log(obj)
            if (obj.type === "done") {
              loading.value = false; // 结束信号：停止加载状态
            } else {
              rawMessages.value.push(obj); // 其他消息：加入原始消息数组
            }
          } catch (e) {
            console.error("解析SSE消息失败:", e, "原始行:", line);
          }
        });
      }
    } catch (e) {
      console.error("搜索过程出错:", e);
      rawMessages.value.push({ 
        type: "text", 
        content: `搜索失败：${e.message}`, 
        newline: true 
      });
      loading.value = false;
    }
  }
  
  
  
  // 搜索参数
  const searchParams = reactive({
    pmid: '',
    title: '',
    author: ''
  });
  
  const trialSearchParams = reactive({
    nctId: '',
    condition: '',
    status: ''
  });
  
  // 所有状态选项及其描述
  const allStatuses = [
    { 
      value: 'ACTIVE_NOT_RECRUITING', 
      label: '活跃但不招募',
      description: '研究正在进行，但不再招募参与者'
    },
    { 
      value: 'COMPLETED', 
      label: '已完成',
      description: '研究已完成所有计划的试验活动'
    },
    { 
      value: 'ENROLLING_BY_INVITATION', 
      label: '邀请招募',
      description: '仅通过邀请招募参与者'
    },
    { 
      value: 'NOT_YET_RECRUITING', 
      label: '尚未招募',
      description: '研究已批准，但尚未开始招募参与者'
    },
    { 
      value: 'RECRUITING', 
      label: '正在招募',
      description: '研究正在积极招募参与者'
    },
    { 
      value: 'SUSPENDED', 
      label: '已暂停',
      description: '研究暂时停止，但可能会恢复'
    },
    { 
      value: 'TERMINATED', 
      label: '已终止',
      description: '研究提前结束，不会恢复'
    },
    { 
      value: 'WITHDRAWN', 
      label: '已撤回',
      description: '研究在开始前被撤回'
    },
    { 
      value: 'AVAILABLE', 
      label: '可获取',
      description: '研究相关资源或数据可获取'
    },
    { 
      value: 'NO_LONGER_AVAILABLE', 
      label: '不再可获取',
      description: '研究相关资源或数据不再可获取'
    },
    { 
      value: 'TEMPORARILY_NOT_AVAILABLE', 
      label: '暂时不可获取',
      description: '研究相关资源或数据暂时不可获取'
    },
    { 
      value: 'APPROVED_FOR_MARKETING', 
      label: '批准上市',
      description: '研究药物或疗法已批准上市'
    },
    { 
      value: 'WITHHELD', 
      label: '已扣留',
      description: '研究信息被扣留'
    },
    { 
      value: 'UNKNOWN', 
      label: '未知',
      description: '研究状态未知'
    }
  ];
  
  // 将英文状态值转换为中文标签
  function formatStatus(statusValue) {
    // 从状态数组中查找匹配的状态对象
    const matchedStatus = allStatuses.find(item => item.value === statusValue);
    
    // 如果找到匹配项，返回中文标签；否则返回原始值（避免显示undefined）
    return matchedStatus ? matchedStatus.label : statusValue;
  }
  
  // 根据状态值返回对应的标签类型
  function statusTagType(statusValue) {
    // 状态类型映射：不同状态对应不同的标签颜色
    const typeMap = {
      // 绿色系（成功/进行中）
      'RECRUITING': 'success',
      'ENROLLING_BY_INVITATION': 'success',
      
      // 蓝色系（信息/已完成）
      'COMPLETED': 'primary',
      'ACTIVE_NOT_RECRUITING': 'info',
      'NOT_YET_RECRUITING': 'info',
      'APPROVED_FOR_MARKETING': 'primary',
      
      // 黄色系（警告/暂时状态）
      'SUSPENDED': 'warning',
      'TEMPORARILY_NOT_AVAILABLE': 'warning',
      
      // 红色系（危险/终止状态）
      'TERMINATED': 'danger',
      'WITHDRAWN': 'danger',
      'NO_LONGER_AVAILABLE': 'danger',
      'WITHHELD': 'danger',
      
      // 灰色系（默认/未知）
      'AVAILABLE': 'default',
      'UNKNOWN': 'default'
    };
    
    // 未匹配到状态时返回默认类型
    return typeMap[statusValue] || 'default';
  }
  
  // 根据状态值获取对应的描述信息
  function getStatusDescription(statusValue) {
    // 从 allStatuses 中匹配状态值
    const matchedStatus = allStatuses.find(item => item.value === statusValue);
    // 有匹配项则返回描述，无匹配项返回默认提示
    return matchedStatus 
      ? matchedStatus.description 
      : `未找到状态「${statusValue}」的描述信息`;
  }
  
  // 获取临床试验数据
  async function fetchTrials() {
    trialLoading.value = true;
    try {
      const url = new URL('/api/clinical_trials', window.location.origin);
      // 添加分页参数
      url.searchParams.append('page', trialPagination.currentPage);
      url.searchParams.append('page_size', trialPagination.pageSize);
      
      // 添加搜索参数
      if (trialSearchParams.nctId) url.searchParams.append('nct_id', trialSearchParams.nctId);
      if (trialSearchParams.condition) url.searchParams.append('condition', trialSearchParams.condition);
      if (trialSearchParams.status) url.searchParams.append('status', trialSearchParams.status);
      
      const res = await fetch(url.toString());
      if (!res.ok) throw new Error('获取数据失败');
      
      const data = await res.json();
      trialList.value = data.items;
      trialPagination.total = data.total;
    } catch (error) {
      console.error('获取临床试验数据失败:', error);
      // 可以添加错误提示
      ElMessage.error('获取临床试验数据失败，请重试');
    } finally {
      trialLoading.value = false;
    }
  }
  
  // 获取文献数据
  async function fetchPapers() {
    paperLoading.value = true;
    try {
      const url = new URL('/api/papers', window.location.origin);
  
      // 添加分页参数
      url.searchParams.append('page', paperPagination.currentPage);
      url.searchParams.append('page_size', paperPagination.pageSize);
      
      // 添加搜索参数
      if (searchParams.pmid) url.searchParams.append('pmid', searchParams.pmid);
      if (searchParams.title) url.searchParams.append('title', searchParams.title);
      if (searchParams.author) url.searchParams.append('author', searchParams.author);
      
      
      const res = await fetch(url.toString());
      const data = await res.json();
      
      paperList.value = data.items;
      paperPagination.total = data.total;
  
    } catch (error) {
      console.error('获取文献数据失败:', error);
    } finally {
      paperLoading.value = false;
    }
  }
  
  // 临床试验分页事件处理
  function handleTrialSizeChange(val) {
    trialPagination.pageSize = val;
    trialPagination.currentPage = 1;
    fetchTrials();
  }
  
  function handleTrialCurrentChange(val) {
    trialPagination.currentPage = val;
    fetchTrials();
  }
  
  // 文献分页事件处理
  function handlePaperSizeChange(val) {
    paperPagination.pageSize = val;
    paperPagination.currentPage = 1;
    fetchPapers();
  }
  
  function handlePaperCurrentChange(val) {
    paperPagination.currentPage = val;
    fetchPapers();
  }
  
  function downloadPDF(path) {
    const encodedPath = encodeURIComponent(path);
    let url = `/api/download/${encodedPath}`;
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.download = "";
    link.click();
  }
  
  // 打开原始来源链接
  function openSourceUrl(url) {
    // 验证URL是否存在且有效
    if (!url) {
      ElMessage.warning('原始链接不存在');
      return;
    }
    
    try {
      // 验证URL格式（简单验证）
      new URL(url);
      
      // 打开链接（在新窗口打开，避免当前页面跳转）
      const newWindow = window.open(url, '_blank');
      
      // 检查浏览器是否阻止了弹窗
      if (!newWindow) {
        ElMessage.warning('链接打开失败，请检查浏览器弹窗设置');
      } else {
        // 聚焦到新打开的窗口
        newWindow.focus();
      }
    } catch (error) {
      // 处理URL格式错误或其他异常
      console.error('打开原始链接失败:', error);
      ElMessage.error('链接格式无效，无法打开');
    }
  }
  
  
  
  // 执行搜索
  function handleTrialSearch() {
    trialPagination.currentPage = 1; // 搜索时重置到第一页
    fetchTrials();
  }
  
  // 重置搜索条件
  function resetTrialSearch() {
    trialSearchParams.nctId = '';
    trialSearchParams.condition = '';
    trialSearchParams.status = '';
    trialPagination.currentPage = 1;
    fetchTrials();
  }
  
  // 执行搜索
  function handlePaperSearch() {
    paperPagination.currentPage = 1; // 搜索时重置到第一页
    fetchPapers();
  }
  
  // 重置搜索条件
  function resetPaperSearch() {
    searchParams.pmid = '';
    searchParams.title = '';
    searchParams.author = '';
    paperPagination.currentPage = 1;
    fetchPapers();
  }
  
  // 监听对话框显示状态，加载对应数据
  watch(showTrialDialog, (newVal) => {
    if (newVal) {
      fetchTrials();
    }
  });
  
  watch(showPaperDialog, (newVal) => {
    if (newVal) {
      fetchPapers();
    }
  });
  
  
  // 点击事件处理函数
  const handleLinkClick = (event) => {
    // 获取元素上的 data 属性（注意 dataset 会自动将连字符转为驼峰命名）
    const eventType = event.currentTarget.dataset.eventType; // 对应 data-event-type
  
    // 校验必要参数
    if (!eventType) {
      console.warn('缺少 event_type ');
      return;
    }
  
    // 根据不同 event_type 执行操作
    switch (eventType) {
      case 'trial':
        const dataIds = event.currentTarget.dataset.ids; // 对应 data-ids
        // 解析 data_ids（假设是逗号分隔的字符串，如"1,2,3"）
        trialSearchParams.nctId = dataIds;
        showTrialDialog.value = true;
        handleTrialSearch()
        break;
      default:
        console.warn(`未处理的事件类型: ${eventType}`);
    }
  };
  
  </script>
  
  <style>
  body {
    font-family: system-ui, sans-serif;
    background-color: #f7f9fc;
    margin: 0;
    padding: 20px;
    display: flex;
    justify-content: center;
  }
  
  .container {
    width: 100%;
    max-width: 1100px; /* PC端更宽 */
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    padding: 30px;
    box-sizing: border-box;
    margin: 0 auto;
  }
  
  h1 {
    margin: 0 0 20px;
    font-size: 24px;
    color: #333;
    text-align: center;
  }
  
  .search-container {
    display: flex;
    gap: 10px;
    margin-bottom: 20px;
  }
  
  .input-span{
    font-size: 14px;
    margin-top: 8px;
    margin-left: 20px;
    text-align: left;
  }
  
  .input-number {
    flex: 0 !important;
  }
  
  input[type="text"], input[type="number"] {
    padding: 10px 12px;
    border: 1px solid #ccc;
    border-radius: 8px;
    font-size: 14px;
    flex: 1;
  }
  
  button {
    padding: 10px 16px;
    background: #4f46e5;
    border: none;
    border-radius: 8px;
    color: #fff;
    font-size: 14px;
    cursor: pointer;
    transition: background 0.2s;
  }
  
  button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  button:hover:not(:disabled) {
    background: #4338ca;
  }
  
  .output {
    background: #f3f4f6;
    border-radius: 8px;
    padding: 16px;
    height: 400px;
    overflow-y: auto;
    font-size: 14px;
    line-height: 1.5;
    color: #111827;
    text-align: left;
  }
  
  .msg {
    margin: 6px 0;
    padding: 8px 12px;
    border-radius: 6px;
    background: #e0e7ff;
    animation: fadeIn 0.3s ease;
  }
  
  /* 图片消息样式（保持与文本消息一致的间距和动画） */
  .msg-img {
    margin: 6px 0;
    border-radius: 6px;
    max-width: 100%;
    animation: fadeIn 0.3s ease;
  }
  
  .msg-link{
    cursor: pointer;
  }
  
  .el-dialog {
    input[type="text"], input[type="number"]{
      border: none
    }
  }
  
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(5px); }
    to { opacity: 1; transform: translateY(0); }
  }
  
  /* 响应式适配 */
  @media (max-width: 768px) {
    .container {
      padding: 20px;
    }
    form {
      flex-direction: column;
    }
    .input-span {
      margin-left: 0;
      margin-top: 0;
      margin-bottom: 4px;
    }
  }
  </style>