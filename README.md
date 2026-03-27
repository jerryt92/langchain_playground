# Langchain Playground

这是一个基于 Python 的多 Agent 运行 playground。

根目录只负责两件事：

- 扫描 `agents/` 下可运行的 agent
- 展示列表并启动你选择的 agent

同时也提供一个 Web 外壳：

- 首页扫描并展示全部 agent
- 选择 agent 后进入浏览器终端，直接透传该 agent 的 `main.py`

每个 agent 的具体能力、依赖、环境变量和使用方式，都写在各自目录下的 `README.md` 中。

## 当前包含的 Agent

- `mysql_assistant`：基于 `ChatOpenAI`（`lib/langchain_model.py` 预配置）的工具调用式 MySQL 助手
- `mysql_assistant_re_act`：基于 LangChain `create_agent` + `ChatAnthropic`（`lib/langchain_model.py` 预配置）的 ReAct 风格 MySQL 助手

## 目录结构

```text
.
├── main.py
├── main_web.py
├── web/
│   ├── index.html
│   ├── terminal.html
│   └── static/
│       ├── css/
│       │   ├── base.css
│       │   ├── home.css
│       │   └── terminal.css
│       └── js/
│           ├── api.js
│           ├── env-editor.js
│           ├── home.js
│           └── terminal.js
├── lib/
│   ├── agent_registry.py  # 统一扫描 agents/*/info.json 与 main.py
│   ├── agent_runtime.py   # 统一交互运行时接口（send_message / wait_input）
│   ├── env_loader.py      # 合并根与 agent 的 .env（进程环境优先）
│   └── langchain_model.py # 预置 ChatOpenAI / ChatAnthropic（仅从根 .env + 进程环境读模型变量）
├── agents/
│   ├── mysql_assistant/
│   │   ├── info.json
│   │   ├── README.md
│   │   ├── .env.example
│   │   ├── main.py
│   │   ├── chat_cli.py
│   │   ├── mysql_assistant.py
│   │   ├── mysql_ops.py
│   │   └── tools.py
│   └── mysql_assistant_re_act/
│       ├── info.json
│       ├── README.md
│       ├── .env.example
│       ├── main.py
│       ├── mysql_ops.py
│       └── tools.py
├── .env.example
└── requirements.txt
```

## 运行约定

- 根目录 `main.py` 是统一入口
- `agents/` 下每个直接子目录都可以视为一个候选 agent
- 只有包含 `main.py` 的 agent 目录才会被自动发现
- 每个 agent 目录都应包含 `info.json`
- 运行器会列出全部 agent，并通过子进程启动对应入口文件
- Web 入口 `main_web.py` 会复用同一份 agent 注册信息
- Web 前端文件已拆分到 `web/` 下，不再内嵌在 `main_web.py` 中

## 安装依赖

```bash
pip install -r requirements.txt
```

## 环境变量

项目根目录 `.env` 用来放公共模型配置（供 `lib/langchain_model.py` 在导入时读取）；agent 自己的 `.env` 用来放该 agent 的专属配置（例如 MySQL、运行开关等，由各 agent 在运行时通过 `load_env_config(project_root, agent_dir)` 合并）。

参考示例：

- 根配置：`.env.example`
- Agent 配置：各 agent 目录下的 `.env.example`

当前根 `.env.example` 里包含两套模型变量（可按需填写其一或全部）：

- `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL`
- `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_API_MODEL`

## 变量优先级

对通过 `load_env_config(project_root, agent_dir)` 合并的配置（例如各 agent 里的 MySQL、运行开关），同名变量覆盖顺序如下：

1. 进程环境变量
2. agent 目录下的 `.env`
3. 项目根目录 `.env`

也就是说，agent 的本地配置会覆盖根配置。

**说明**：`lib/langchain_model.py` 在导入时只调用 `load_env_config(project_root)`，模型 API 相关变量以**项目根 `.env` 与进程环境**为准，不受 agent 目录 `.env` 覆盖。

## 运行方式

启动统一运行器：

```bash
python main.py
```

运行后会看到类似下面的列表：

```text
已注册的 agents：
1. MySQL Assistant (mysql_assistant) - 基于 ChatOpenAI 的 MySQL 工具调用式智能体。
2. MySQL Assistant ReAct (mysql_assistant_re_act) - 基于 create_agent 和 ChatAnthropic 的 MySQL ReAct 智能体。
```

输入编号后，运行器会启动对应 agent。

如果你已经确定要运行哪个 agent，也可以直接执行该 agent 目录下的 `main.py`。

## Web 运行方式

启动 Web 外壳：

```bash
python main_web.py
```

默认监听在 `http://127.0.0.1:8000`。

也支持直接传参：

```bash
python main_web.py --host 0.0.0.0 --port 9001
```

使用方式：

1. 打开首页，查看自动扫描到的 agent 卡片
2. 在首页右侧编辑项目根目录 `.env`，顶部提供“刷新 / 保存”按钮
3. 点击一个 agent
4. 进入浏览器终端，直接与该 agent 的 `main.py` 交互
5. 在 agent 页面右侧编辑该 agent 目录下的 `.env`，顶部同样提供“刷新 / 保存”按钮

终端页会通过 WebSocket + PTY 透传 `stdin/stdout/stderr`，因此 `exit`、`clear` 等原有 CLI 命令保持不变。

## 新增 Agent

新增 agent 时，遵循下面的约定：

1. 在 `agents/` 下创建新子目录，例如 `agents/demo_agent`
2. 在该目录中创建 `info.json`
3. 在该目录中创建 `main.py`
4. 在该目录中创建 `README.md`
5. 如有专属配置，补充 `.env.example`

最小结构示例：

```text
agents/
└── demo_agent/
    ├── info.json
    ├── README.md
    └── main.py
```

`info.json` 约定如下：

```json
{
  "agent_id": "demo_agent",
  "name": "Demo Agent",
  "description": "这里填写 agent 的简要说明。"
}
```

约定说明：

- `agent_id` 建议与目录名保持一致
- `name` 用于 CLI 和 Web 展示
- `description` 用于 CLI 列表和 Web 卡片描述

## Agent 文档

- `agents/mysql_assistant/README.md`
- `agents/mysql_assistant_re_act/README.md`
