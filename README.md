# 项目说明

## 项目结构
- 前端代码：位于 `frontend` 目录，基于 Vue3 + ElementUI 开发
- 后端代码：位于项目根目录，基于 FastAPI 开发

## 前端部分

### 环境安装
```bash
cd frontend
npm install
```

### 开发环境运行
```bash
npm run dev
```

### 与后端集成部署
1. 修改 `vite.config.js` 配置代理：
```javascript
export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000' // 如果部署在公网，需修改为正式服务端地址
    }
  }
})
```

2. 构建前端静态文件：
```bash
npm run build
```
构建完成后会生成 `dist/` 目录

3. 在 FastAPI 中挂载前端静态文件：
```python
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")
```

## 后端部分

### 技术框架
- 基于 FastAPI 构建
- 支持异步数据库操作

### 配置说明
1. 配置文件为项目根目录下的 `.env` 文件，使用前请根据实际环境修改
2. 主要配置项说明：
   - 数据库连接配置（MySQL 或 SQLite）
   - NCBI 服务访问配置（工具名、邮箱、API 密钥）
   - PDF 存储目录配置

### 启动方式
1. 安装依赖：
```bash
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

2. 启动服务：
```bash
# 开发环境
uvicorn main:app --reload

# 生产环境（示例）
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 部署说明
- 可使用 Gunicorn 作为生产环境的 WSGI 服务器
- 配合 Nginx 作为反向代理和静态资源服务器
- 确保 `.env` 文件中的配置与生产环境一致，特别是数据库连接和存储路径

## 注意事项
- 首次运行前请确保配置文件 `.env` 已正确设置
- 生产环境中建议使用 MySQL 数据库，并妥善保管 NCBI API 密钥
- PDF 存储目录需要有适当的读写权限