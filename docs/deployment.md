# 部署说明

这个项目建议采用“后端 Render + 前端 Vercel”的方式上线。完整本地数据库不要上传到 GitHub；线上会在第一次启动时使用 `backend/app/data/demo_seed.json` 自动生成一个小型演示数据库，面试官打开网页就能直接体验。

## 1. 推送到 GitHub

在 `E:\agnet\shopcare-agent` 中执行：

```bash
git add .
git commit -m "feat: build shopcare aftersales agent"
git branch -M main
git remote add origin https://github.com/你的用户名/shopcare-agent.git
git push -u origin main
```

注意：`.env`、完整 CSV、完整 SQLite 数据库已经被 `.gitignore` 排除，不要手动上传。

## 2. 部署后端到 Render

1. 打开 Render，新建 `Web Service`。
2. 连接你的 GitHub 仓库 `shopcare-agent`。
3. 如果 Render 识别到 `render.yaml`，直接使用 Blueprint。
4. 如果手动配置：
   - Root Directory: `backend`
   - Runtime: `Python`
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. 添加环境变量：
   - `APP_ENV=production`
   - `SHOPCARE_DB_PATH=./data/shopcare.db`
   - `LLM_PROVIDER=deepseek`
   - `LLM_BASE_URL=https://api.deepseek.com`
   - `LLM_MODEL=deepseek-chat`
   - `LLM_API_KEY=你的 API Key`
   - `ALLOW_ORIGINS=https://你的前端域名.vercel.app`

部署成功后，先访问：

```text
https://你的后端域名.onrender.com/health
```

看到 `{"status":"ok"}` 就说明后端成功。

## 3. 部署前端到 Vercel

1. 打开 Vercel，新建 Project。
2. 选择同一个 GitHub 仓库。
3. Root Directory 选择 `frontend`。
4. Build Command 使用 `npm run build`。
5. Output Directory 使用 `dist`。
6. 添加环境变量：
   - `VITE_API_BASE_URL=https://你的后端域名.onrender.com`

部署完成后，把 Vercel 生成的前端域名复制回来，更新 Render 后端的 `ALLOW_ORIGINS`，然后重新部署后端。

## 4. 本地和线上数据策略

- 本地演示：使用完整 `shopcare.db`，可以展示 38 万订单、9.8 万用户和约 4 万售后案例。
- 线上简历 demo：使用 `demo_seed.json` 自动生成小型 SQLite，方便公开访问。
- 后续增强：如果要做长期在线版本，建议把 SQLite 换成 PostgreSQL，并把数据导入云数据库。

## 5. 验收清单

- 后端 `/health` 返回 `ok`。
- 前端能打开并显示订单、用户、售后 KPI。
- 输入订单号 `3000012` 和售后问题，页面能显示 Agent 答复、决策结果、工具调用轨迹。
- 后端返回里的 `llm_used` 为 `true`，说明 API 已经参与回答生成。
