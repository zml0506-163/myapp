"""
优化的 LLM 服务 - 统一上下文处理
app/services/llm_service.py
"""
import logging
import os
import base64
from typing import AsyncGenerator, Optional, List, Dict, Any, Union
from openai import AsyncOpenAI

from app.core.config import settings


class MessageBuilder:
    """消息构建器 - 统一处理普通对话和文件上下文"""

    def __init__(self):
        self.messages: List[Dict[str, Any]] = []
        self.file_ids: List[str] = []
        self.system_prompt: str = "你是一个专业的医疗问答助手。"

    def set_system_prompt(self, prompt: str) -> 'MessageBuilder':
        """设置系统提示词"""
        self.system_prompt = prompt
        return self

    def add_file_ids(self, file_ids: List[str]) -> 'MessageBuilder':
        """添加文件ID（用于qwen-long）"""
        self.file_ids.extend(file_ids)
        return self

    def add_history(self, history: List[Dict[str, Any]]) -> 'MessageBuilder':
        """添加历史对话"""
        self.messages.extend(history)
        return self

    def add_user_message(self, content: str) -> 'MessageBuilder':
        """添加用户消息"""
        self.messages.append({"role": "user", "content": content})
        return self

    def add_assistant_message(self, content: str) -> 'MessageBuilder':
        """添加助手消息"""
        self.messages.append({"role": "assistant", "content": content})
        return self

    def build(self) -> List[Dict[str, Any]]:
        """
        构建最终的消息列表

        格式：
        [
            {'role': 'system', 'content': '系统提示词'},
            {'role': 'system', 'content': 'fileid://xxx,fileid://yyy'},  # 如果有文件
            {'role': 'user', 'content': '...'},
            {'role': 'assistant', 'content': '...'},
            ...
        ]
        """
        result: List[Dict[str, Any]] = []

        # 1. 添加系统提示词
        result.append({"role": "system", "content": self.system_prompt})

        # 2. 添加历史消息（包括附件上下文）
        result.extend(self.messages)

        # 3. 如果有文件ID，添加文件上下文（在最后）
        if self.file_ids:
            file_context = ",".join([f"fileid://{fid}" for fid in self.file_ids])
            result.append({"role": "system", "content": file_context})

        return result


class LLMService:
    """大模型服务 - 支持不同模型的调用"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )

    async def chat_stream(
            self,
            messages: List[Dict[str, Any]],
            model: Optional[str] = None,
            temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """
        通用流式对话

        Args:
            messages: 完整的消息列表（已包含system、file context等）
            model: 模型名称
            temperature: 温度参数
        """
        if model is None:
            model = settings.qwen_max_model

        try:
            completion = await self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore
                stream=True,
                temperature=temperature,
            )

            async for chunk in completion:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logging.exception(e)
            error_msg = str(e)
            
            # 提取更友好的错误信息
            if hasattr(e, 'response') and e.response is not None:  # type: ignore
                try:
                    error_data = e.response.json()  # type: ignore
                    error_msg = error_data.get('error', {}).get('message', str(e))
                except:
                    pass
            
            # 判断是否是配额耗尽错误
            if 'AllocationQuota' in str(e) or 'FreeTierOnly' in str(e):
                error_msg = "模型免费额度已用完,请在阿里云控制台开通付费服务或关闭'仅使用免费额度'模式"
            
            yield f"\n❌ 模型调用失败: {error_msg}\n"
            # 抛出异常，让上层捕获
            raise

    async def chat_with_context(
            self,
            user_query: str,
            history: Optional[List[Dict[str, Any]]] = None,
            file_ids: Optional[List[str]] = None,
            system_prompt: Optional[str] = None,
            model: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        统一的上下文对话接口

        Args:
            user_query: 用户问题
            history: 历史对话 [{"role": "user", "content": "..."}, ...]
            file_ids: 文件ID列表（用于qwen-long）
            system_prompt: 系统提示词
            model: 模型名称
        """
        # 使用消息构建器
        builder = MessageBuilder()

        if system_prompt:
            builder.set_system_prompt(system_prompt)

        if file_ids:
            builder.add_file_ids(file_ids)
            # 有文件时使用 qwen-long
            model = model or settings.qwen_long_model
        else:
            model = model or settings.qwen_max_model

        if history:
            builder.add_history(history)

        builder.add_user_message(user_query)

        messages = builder.build()

        # 调用流式接口
        async for chunk in self.chat_stream(messages=messages, model=model):
            yield chunk

    async def chat_with_image_stream(
            self,
            text: str,
            image_path: str,
            history: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[str, None]:
        """
        基于图片的流式对话（使用 qwen3-vl-plus）

        注意：图片模型不支持file_id方式，需要base64编码
        """
        # 编码图片
        with open(image_path, "rb") as f:
            base64_image = base64.b64encode(f.read()).decode("utf-8")

        # 判断图片格式
        ext = os.path.splitext(image_path)[1].lower()
        mime_type = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
        }.get(ext, 'image/png')

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": "你是一个专业的图像分析助手。"}
        ]

        if history:
            messages.extend(history)

        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                },
                {"type": "text", "text": text}
            ]
        })

        try:
            completion = await self.client.chat.completions.create(
                model=settings.qwen_vl_model,
                messages=messages,  # type: ignore
                stream=True,
            )

            async for chunk in completion:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            error_msg = str(e)
            
            # 提取更友好的错误信息
            if hasattr(e, 'response') and e.response is not None:  # type: ignore
                try:
                    error_data = e.response.json()  # type: ignore
                    error_msg = error_data.get('error', {}).get('message', str(e))
                except:
                    pass
            
            # 判断是否是配额耗尽错误
            if 'AllocationQuota' in str(e) or 'FreeTierOnly' in str(e):
                error_msg = "VL模型免费额度已用完,请在阿里云控制台开通付费服务"
            
            yield f"\n❌ 视觉模型调用失败: {error_msg}\n"
            raise


# 全局实例
llm_service = LLMService()