import os
from pypdf import PdfReader

class PDFService:
    """PDF 文件解析服务"""

    @staticmethod
    def extract_text(pdf_path: str, max_length: int = 50000) -> str:
        """
        从 PDF 提取文本

        Args:
            pdf_path: PDF 文件路径
            max_length: 最大提取长度（防止超过 LLM 限制）

        Returns:
            提取的文本内容
        """
        if not os.path.exists(pdf_path):
            return f"[文件不存在: {pdf_path}]"

        try:
            reader = PdfReader(pdf_path)
            text = ""

            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

                # 限制长度
                if len(text) >= max_length:
                    text = text[:max_length]
                    text += "\n\n[文本已截断...]"
                    break

            return text

        except Exception as e:
            return f"[PDF 解析失败: {str(e)}]"

pdf_service = PDFService()