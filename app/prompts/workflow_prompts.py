"""
工作流提示词模板
"""


class WorkflowPrompts:
    """工作流提示词管理类"""

    @staticmethod
    def extract_features(context: str, user_query: str) -> str:
        """提取患者特征的提示词"""
        return f"""{context}

### 当前用户问题
{user_query}

### 任务
请从以上信息中提取患者的关键特征，包括：

1. **主要疾病/诊断**: 明确患者的主要疾病名称
2. **病理类型和分期**: 如果提到，请列出详细的病理类型和TNM分期
3. **基因突变信息**: 列出所有提到的基因突变（如EGFR、ALK、ROS1等）
4. **既往治疗史**: 之前接受过的治疗方案
5. **当前状态和需求**: 患者目前的状态和想了解的内容

请以结构化、清晰的方式列出这些信息。如果某些信息未提及，请标注"未提及"。"""

    @staticmethod
    def generate_queries(patient_features: str) -> str:
        """生成检索条件的提示词"""
        return f"""基于以下患者特征，生成精确的检索条件：

### 患者特征
{patient_features}

### 任务
请生成以下检索条件：

1. **PubMed 检索表达式**: 使用布尔运算符（AND、OR），构建精确的检索式，确保能检索到相关文献
2. **ClinicalTrials.gov 关键词**: 提取3-5个核心关键词，用逗号分隔

**输出格式（必须严格遵守JSON格式）**:
```json
{{
    "pubmed_query": "这里是PubMed检索表达式",
    "clinical_trial_keywords": "关键词1,关键词2,关键词3"
}}
```

只输出JSON，不要有其他内容。"""

    @staticmethod
    def analyze_paper(patient_features: str, user_query: str, paper: dict) -> str:
        """分析单篇文献的提示词"""
        return f"""请仔细阅读这篇PDF文献，并基于以下信息进行深入分析：

### 患者特征
{patient_features}

### 用户问题
{user_query}

### 文献基本信息
- **标题**: {paper['title']}
- **作者**: {paper.get('authors', 'N/A')}
- **发表日期**: {paper.get('pub_date', 'N/A')}

### 分析任务
请完成以下分析（基于PDF全文）：

1. **文献核心内容概述**: 简要说明文献的主要研究内容
2. **与患者情况的相关性**: 分析该文献与患者情况的相关程度（0-100分）
3. **主要发现和结论**: 列出文献的关键发现
4. **证据等级评估**: 评估该研究的证据级别（如RCT、回顾性研究等）
5. **对患者的临床意义**: 说明该文献对患者的实际指导意义

**重要输出要求**：
- 使用Markdown格式输出
- 关键数据使用**表格**呈现（如疗效数据、副作用发生率等）
- 表格示例：

| 指标 | 数值 | 说明 |
|------|------|------|
| 客观缓解率(ORR) | 70% | 肿瘤明显缩小的患者比例 |
| 无进展生存期(PFS) | 12个月 | 中位无进展生存期 |

- 使用**加粗**突出重要信息
- 使用项目列表使内容结构清晰"""

    @staticmethod
    def analyze_trials(patient_features: str, trials_text: str) -> str:
        """分析临床试验的提示词"""
        return f"""基于患者特征评估以下临床试验的适配性：

### 患者特征
{patient_features}

### 临床试验列表
{trials_text}

### 分析任务
请针对每个试验进行评估：

1. **适配度评分** (0-100分): 评估该试验与患者的匹配程度
2. **入组标准分析**: 分析患者是否符合入组条件
3. **排除标准考量**: 评估是否存在排除因素
4. **试验优势**: 说明该试验的优势和特点
5. **潜在风险**: 提示可能的风险
6. **推荐等级**: 给出推荐级别（强烈推荐/推荐/谨慎推荐/不推荐）

最后给出**综合建议**，说明最适合的1-2个试验。"""

    @staticmethod
    def generate_final_report(
            user_query: str,
            patient_features: str,
            papers_summary: str,
            trial_analysis: str
    ) -> str:
        """生成最终报告的提示词"""
        return f"""请基于所有分析生成一份结构化的最终报告：

### 原始问题
{user_query}

### 患者特征摘要
{patient_features[:500]}...

### 文献分析汇总
{papers_summary}

### 临床试验分析摘要
{trial_analysis[:500] if trial_analysis else "暂无"}...

### 报告要求
请生成一份专业的医疗咨询报告，包含：

1. **执行摘要**: 简要总结本次分析的核心内容
2. **治疗方案建议**: 基于文献分析，提供治疗方案建议
3. **临床试验推荐**: 推荐最适合的1-2个临床试验
4. **注意事项**: 提示需要注意的风险和问题
5. **后续行动建议**: 给出具体的下一步建议

请保持专业、客观，使用易懂的语言。"""