import os
import base64
from typing import AsyncGenerator, Optional
from openai import OpenAI, AsyncOpenAI

from app.core.config import settings


class LLMService:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )
        self.sync_client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
        )

    async def chat_stream(
            self,
            messages: list[dict],
            model: str = None,
            system_prompt: str = "你是一个专业的医疗问答助手。"
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        if model is None:
            model = settings.qwen_max_model

        # 添加系统提示
        full_messages = [{"role": "system", "content": system_prompt}]
        full_messages.extend(messages)

        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=full_messages,
                stream=True,
                temperature=0.7,
            )

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[错误] {str(e)}\n"

    async def chat_with_image_stream(
            self,
            text: str,
            image_path: str,
            history: list[dict] = None
    ) -> AsyncGenerator[str, None]:
        """带图片的流式对话"""
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
            stream = await self.client.chat.completions.create(
                model=settings.qwen_vl_model,
                messages=messages,
                stream=True,
            )

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            yield f"\n[错误] {str(e)}\n"

    async def chat_with_documents_stream(
            self,
            text: str,
            document_content: str,
            history: list[dict] = None
    ) -> AsyncGenerator[str, None]:
        """带文档的流式对话（使用 qwen-long）"""
        messages = []
        if history:
            messages.extend(history)

        # 将文档内容作为上下文
        context_message = f"""以下是参考文档内容：

{document_content}

---

用户问题：{text}
"""

        messages.append({"role": "user", "content": context_message})

        async for chunk in self.chat_stream(
                messages=messages,
                model=settings.qwen_long_model,
                system_prompt="你是一个专业的医疗文献分析助手。请基于提供的文档内容回答问题。"
        ):
            yield chunk

llm_service = LLMService()