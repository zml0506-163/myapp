Vue3 + ElementUI

安装环境
```
cd frontend
npm install
```
前端开发环境独立运行：
```
npm run dev
```

集成到Python 与 Fastapi一起运行
```
1） 在vite.config.js增加
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'  # 记得修改为真实地址
    }
  }
})

2）npm run build 会生成 dist/

3）可以直接在 FastAPI 里挂载静态目录：
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

```
