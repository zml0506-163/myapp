import os
import base64
from typing import AsyncGenerator, Optional, List
from openai import AsyncOpenAI

from app.core.config import settings


class LLMService:
    """大模型服务 - 支持不同模型的调用"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )

    async def chat_stream(
            self,
            messages: List[dict],
            model: str = None,
            system_prompt: str = "你是一个专业的医疗问答助手。"
    ) -> AsyncGenerator[str, None]:
        """
        通用流式对话

        Args:
            messages: 对话历史，格式 [{"role": "user", "content": "..."}]
            model: 模型名称，默认使用 qwen-max
            system_prompt: 系统提示词
        """
        if model is None:
            model = settings.qwen_max_model

        # 构建完整消息列表
        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(messages)

        try:
            completion = await self.client.chat.completions.create(
                model=model,
                messages=full_messages,
                stream=True,
                temperature=0.7,
            )

            async for chunk in completion:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[错误] 模型调用失败: {str(e)}\n"

    async def chat_with_pdf_stream(
            self,
            text: str,
            pdf_path: str,
            history: List[dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        基于 PDF 的流式对话（使用 qwen-long）
        注意：qwen-long 支持直接上传文件，无需提取文本

        Args:
            text: 用户问题
            pdf_path: PDF 文件路径
            history: 历史对话
        """
        messages = []
        if history:
            messages.extend(history)

        # qwen-long 支持文件上传，将 PDF 作为文件附件
        # 读取 PDF 并转换为 base64
        with open(pdf_path, "rb") as f:
            pdf_base64 = base64.b64encode(f.read()).decode("utf-8")

        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "file",
                    "file_url": {
                        "url": f"data:application/pdf;base64,{pdf_base64}"
                    }
                },
                {"type": "text", "text": text}
            ]
        })

        async for chunk in self.chat_stream(
                messages=messages,
                model=settings.qwen_long_model,
                system_prompt="你是一个专业的医疗文献分析助手。请仔细阅读提供的PDF文档，并基于文档内容回答问题。"
        ):
            yield chunk

    async def chat_with_image_stream(
            self,
            text: str,
            image_path: str,
            history: List[dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        基于图片的流式对话（使用 qwen3-vl-plus）

        Args:
            text: 用户问题
            image_path: 图片路径
            history: 历史对话
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

        messages = []
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
                messages=messages,
                stream=True,
            )

            async for chunk in completion:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[错误] 视觉模型调用失败: {str(e)}\n"

    async def chat_with_multiple_pdfs_stream(
            self,
            text: str,
            pdf_paths: List[str],
            history: List[dict] = None
    ) -> AsyncGenerator[str, None]:
        """
        基于多个 PDF 的流式对话（使用 qwen-long）

        Args:
            text: 用户问题
            pdf_paths: PDF 文件路径列表
            history: 历史对话
        """
        messages = []
        if history:
            messages.extend(history)

        # 构建包含多个文件的消息
        content = []

        # 添加所有 PDF 文件
        for pdf_path in pdf_paths:
            with open(pdf_path, "rb") as f:
                pdf_base64 = base64.b64encode(f.read()).decode("utf-8")

            content.append({
                "type": "file",
                "file_url": {
                    "url": f"data:application/pdf;base64,{pdf_base64}"
                }
            })

        # 添加用户问题
        content.append({"type": "text", "text": text})

        messages.append({
            "role": "user",
            "content": content
        })

        async for chunk in self.chat_stream(
                messages=messages,
                model=settings.qwen_long_model,
                system_prompt="你是一个专业的医疗文献分析助手。请仔细阅读所有提供的PDF文档，并基于文档内容进行综合分析和回答。"
        ):
            yield chunk


llm_service = LLMService()