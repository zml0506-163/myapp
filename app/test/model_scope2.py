import base64
import os

from openai import OpenAI

client = OpenAI(
    base_url='https://api-inference.modelscope.cn/v1',
    api_key='ms-77ee9528-ed46-4605-abf2-abf966d525a1', # ModelScope Token
)

image_path = "C:\\Users\\Administrator\\Desktop\\测试数据\\case 2\\case2-时间轴+报告解读.png"
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





response = client.chat.completions.create(
    model='Qwen/Qwen3-VL-235B-A22B-Instruct', # ModelScope Model-Id, required
    messages=[{
        'role':
            'user',
        'content': [{
            'type': 'text',
            'text': '总结这张图片的内容',
        }, {
            'type': 'image_url',
            'image_url': {"url": f"data:{mime_type};base64,{base64_image}"},
        }],
    }],
    stream=True
)

for chunk in response:
    print(chunk.choices[0].delta.content, end='', flush=True)