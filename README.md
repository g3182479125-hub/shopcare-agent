# ShopCare Agent

ShopCare Agent 是一个面向电商售后的智能问答与决策系统。项目基于订单、用户和售后案例数据，提供订单查询、用户画像、相似售后案例检索、售后政策检索、处理方案决策和可解释 Agent 调用轨迹展示。

## 项目亮点

- 基于 38 万订单、9.8 万用户和约 4 万售后工单案例构建业务数据底座。
- 采用 ReAct 思路组织 Agent：识别意图、查询订单、查询用户、检索案例、检索政策、生成售后决策。
- 支持 DeepSeek/OpenAI 兼容 API；没有 API Key 时仍可用规则引擎兜底。
- 前端展示 Agent 工具调用轨迹，方便面试时解释系统不是简单聊天机器人。
- 支持公网部署：后端 Render/Railway，前端 Vercel。

## 在线演示

- GitHub 仓库：https://github.com/g3182479125-hub/shopcare-agent
- 公网 Demo：https://g3182479125-hub.github.io/shopcare-agent/

公网 Demo 使用完全合成的示例数据，并内置前端兜底 Agent 流程；本地环境和后续 Render 后端部署后，会优先调用真实 FastAPI + LLM 接口。

## 技术栈

- Backend: FastAPI, SQLite, OpenAI-compatible SDK
- Frontend: React, Vite, TypeScript, lucide-react
- Agent: intent routing, tool calling, policy RAG, case retrieval, rule decision, LLM response rewrite

## 快速启动

### 1. 导入完整数据

```bash
cd E:\agnet\shopcare-agent\backend
python scripts\import_data.py
```

脚本会优先读取 `.env` 中的数据路径；如果没有配置，会自动在 `E:/agnet` 下查找 `order.csv`、`user.csv` 和 `aftersales_cases.csv`。

### 2. 配置 API Key

```bash
cd E:\agnet\shopcare-agent\backend
copy .env.example .env
```

然后在 `.env` 中填写：

```env
LLM_PROVIDER=deepseek
LLM_API_KEY=你的 API Key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

### 3. 启动后端

```bash
cd E:\agnet\shopcare-agent\backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

接口文档：

```text
http://localhost:8000/docs
```

### 4. 启动前端

```bash
cd E:\agnet\shopcare-agent\frontend
npm install
npm run dev
```

页面地址：

```text
http://localhost:5173
```



## 图片凭证与视觉 Agent

系统支持在售后问题输入框中粘贴、拖拽或上传一张商品问题图片。前端会用 `multipart/form-data` 提交图片，后端先调用 `ImageAnalysisAgent` 进行视觉分析，再把图片分析结果注入原有订单查询、政策 RAG、相似案例检索和售后决策流程。

图片分析使用 Kimi 视觉模型，相关环境变量：

```env
KIMI_API_KEY=
KIMI_BASE_URL=https://api.moonshot.cn/v1
KIMI_MODEL=moonshot-v1-8k-vision-preview
```

没有配置 `KIMI_API_KEY` 或 Kimi 调用失败时，系统会在工具轨迹中记录错误，并继续执行原有售后决策流程。

## 公网部署

具体步骤见 `docs/deployment.md`。推荐：

- 后端：Render Web Service 或 Vercel FastAPI 后端
- 前端：Vercel
- 线上 demo 数据：`backend/app/data/demo_seed.json` 自动初始化

## 简历描述建议

设计并实现 ShopCare Agent 电商售后智能决策系统，基于 38 万订单、9.8 万用户及 4 万售后工单构建业务数据底座；采用 ReAct 工具调用流程，实现订单查询、用户画像、相似案例检索、售后政策 RAG、退款/退货/换货/补发/人工升级决策，并通过前端展示 Agent 调用轨迹和决策依据。系统采用 FastAPI + React + SQLite 工程化实现，支持 DeepSeek/OpenAI 兼容 API 扩展和公网部署。

## Agent Runtime 优化

系统参考 Claude Code 的 Agent Runtime 思路，将售后处理拆成可观测的五层：

- ContextManager：合并当前问题、浏览器传入的会话历史和后端短期记忆，支持多人并发隔离。
- PlanningAgent：根据是否有图片、是否有订单号和售后意图生成执行计划。
- Tool Runtime：订单查询、用户画像、政策 RAG、相似案例和决策工具统一输出 ToolTrace。
- DecisionGuardrail：对退款金额、订单状态、优先级等关键字段做二次校验，避免模型或规则越权。
- Response Layer：图片场景走 Kimi 多模态；纯文本场景走 DeepSeek；模型不可用时由规则答复兜底。

