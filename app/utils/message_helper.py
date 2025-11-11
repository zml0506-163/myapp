"""
消息助手 - 处理事件存储和内容重建
app/utils/message_helper.py
"""
import json
from typing import List, Dict, Any


def reconstruct_content_from_events(events: List[Dict]) -> str:
    """从事件数组重建完整内容（用于持久化到数据库）"""
    
    # 检查是否是工作流模式
    has_sections = any(e.get('type') == 'section_start' for e in events)
    
    if has_sections:
        # 工作流模式：提取有意义的内容，而不是调试数据
        content_parts = []
        current_section_title = None
        
        for event in events:
            if event['type'] == 'section_start':
                current_section_title = event.get('title', '')
                content_parts.append(f"\n## {current_section_title}\n")
            
            elif event['type'] == 'result':
                # 只保存最终结果，忽略增量内容
                if not event.get('is_incremental'):
                    result_content = event.get('content', '')
                    if result_content.strip():
                        content_parts.append(result_content)
                        content_parts.append("\n")
            
            elif event['type'] == 'token':
                # 最终报告的 token
                content_parts.append(event['content'])
        
        return ''.join(content_parts).strip()
    
    else:
        # 普通模式：拼接所有 token
        content = ""
        for event in events:
            if event['type'] == 'token':
                content += event['content']
        return content
