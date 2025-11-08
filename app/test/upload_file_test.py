import os
from pathlib import Path
from openai import OpenAI, NotFoundError, APIError

# 初始化客户端（适配 DashScope 兼容接口）
client = OpenAI(
    api_key="sk-8f7373b5086249e3b0db5bb3609cc909",  # 从环境变量获取API密钥
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"  # DashScope兼容地址
)

def upload_file(file_path, purpose="assistants"):
    """上传文件并返回文件ID"""
    try:
        # 检查文件是否存在
        file = Path(file_path)
        if not file.exists():
            raise FileNotFoundError(f"本地文件不存在：{file_path}")

        # 上传文件（注意：DashScope可能对purpose有特定要求，需参考其文档）
        file_object = client.files.create(
            file=file,
            purpose=purpose  # 建议使用OpenAI标准purpose（如assistants），避免自定义值
        )
        print(f"文件上传成功！文件ID：{file_object.id}")
        return file_object.id  # 返回上传后的文件ID
    except APIError as e:
        print(f"上传失败：API错误 - {str(e)}")
        return None
    except Exception as e:
        print(f"上传失败：{str(e)}")
        return None

def check_file_exists(file_id):
    """查询文件ID是否存在，返回文件信息或None"""
    if not file_id:
        print("文件ID不能为空")
        return None

    try:
        # 查询文件信息
        file_info = client.files.retrieve(file_id=file_id)
        print(f"\n文件存在！状态：{file_info.status}")
        print(f"文件详情：{file_info}")
        return file_info
    except NotFoundError:
        print(f"\n文件ID不存在或已删除：{file_id}")
        return None
    except APIError as e:
        print(f"查询失败：API错误 - {str(e)}")
        return None
    except Exception as e:
        print(f"查询失败：{str(e)}")
        return None

# 示例用法
if __name__ == "__main__":
    # 1. 上传文件（替换为你的文件路径）
    uploaded_file_id = upload_file(
        file_path="C:\\Users\\Administrator\\Desktop\\测试数据\\case 2\\case2-时间轴+报告解读.png",
        purpose="file-extract"  # 若DashScope有特定purpose，需修改为其支持的值
    )

    # 2. 若上传成功，查询文件状态
    if uploaded_file_id:
        check_file_exists("123")