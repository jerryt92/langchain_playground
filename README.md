# Langchain Playground

这是一个基于 Python 的 Langchain Agent 运行器。

根目录只负责两件事：

- 扫描 `agents` 下的可运行 agent
- 列出并启动你选择的 agent

各个 agent 的专属说明、环境变量和使用方式，放在各自目录下的 `README.md` 中。

## 目录结构

```text
.
├── main.py
├── lib/
├── agents/
│   └── mysql_assistant/
│       ├── README.md
│       ├── main.py
│       └── mysql_assistant.py
├── .env.example
└── requirements.txt
```

## 运行约定

- 根目录 `main.py` 是统一入口
- `agents` 目录下的每个直接子目录代表一个 agent
- 只有包含 `main.py` 的 agent 目录才会被识别并展示
- 运行器会列出所有已注册 agent，选择后用子进程启动对应入口

## 安装依赖

```bash
pip install -r requirements.txt
```

## 公共环境变量

项目根目录 `.env` 用来放公共配置，当前主要是模型相关变量。

参考示例：

- `.env.example`

推荐放置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

## 变量优先级

如果出现同名变量，覆盖顺序是：

1. 进程环境变量
2. agent 目录下的 `.env`
3. 项目根目录的 `.env`

## 运行方式

启动统一运行器：

```bash
python main.py
```

运行后会显示已发现的 agent 列表，例如：

```text
已注册的 agents：
1. mysql_assistant
```

输入编号后，运行器会启动对应 agent。

## 新增 Agent

新增 agent 时，遵循下面的约定：

1. 在 `agents` 下创建一个新子目录，例如 `agents/demo_agent`
2. 在该目录中创建 `main.py`
3. 在该目录中创建 `README.md`，写清这个 agent 的用途、依赖和环境变量

最小结构示例：

```text
agents/
└── demo_agent/
    ├── README.md
    └── main.py
```

## Agent 文档

当前 agent 文档：

- `agents/mysql_assistant/README.md`
