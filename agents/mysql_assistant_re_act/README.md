# mysql_assistant_2

`mysql_assistant_2` 是一个基于 LangChain `create_agent` 的 MySQL 工具智能体。

它不再依赖自定义 `MySQLAssistant` 类，而是直接使用 LangGraph 驱动的生产级 agent runtime：

- 模型在循环里自主决定是否调用工具
- 工具调用结果会自动回流到后续推理
- 直到模型给出最终答案或运行结束

## 核心实现

- `chat_cli.py`：读取配置、创建 `create_agent` 智能体、维护 CLI 会话消息
- `tools.py`：注册 `list_databases`、`list_tables`、`get_table_schema`、`run_sql`
- `mysql_ops.py`：负责 MySQL 连接、元数据查询、SQL 安全校验和执行
- `main.py`：启动入口

当前 agent 的系统提示会约束模型：

- 先探索库、表、字段，再执行 SQL
- 禁止使用 `USE 数据库名`
- 一次只允许执行一条 SQL
- 只读模式下仅允许 `SELECT` / `WITH`

另外还加了工具错误中间件，工具异常会作为 `ToolMessage` 返回给模型，方便模型自动修正输入后重试。

## 入口

```bash
python agents/mysql_assistant_re_act/main.py
```

单次提问：

```bash
python agents/mysql_assistant_re_act/main.py "当前实例有哪些数据库"
```

交互模式下：

- 输入 `exit`、`quit` 或 `q` 退出
- 输入 `clear` 或 `reset` 清空当前会话消息

## 环境变量

这个 agent 使用“项目根 `.env` + agent 目录 `.env`”两层配置。

根 `.env` 常用模型配置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`（可选）
- `OPENAI_MODEL`（可选，默认 `gpt-4o-mini`）

`agents/mysql_assistant_2/.env` 常用数据库配置：

- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`（可选）
- `MYSQL_CHARSET`
- `MYSQL_CONNECT_TIMEOUT`
- `MYSQL_READ_TIMEOUT`
- `MYSQL_WRITE_TIMEOUT`
- `ALLOW_WRITE`
- `INCLUDE_TABLES`
- `PRINT_MODEL_OUTPUT`

参考示例：

```bash
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD='123456'
# MYSQL_DATABASE=your_database_name
MYSQL_CHARSET=utf8mb4
MYSQL_CONNECT_TIMEOUT=30
MYSQL_READ_TIMEOUT=30
MYSQL_WRITE_TIMEOUT=30
ALLOW_WRITE=false
INCLUDE_TABLES=
PRINT_MODEL_OUTPUT=false
```

说明：

- `INCLUDE_TABLES` 支持 `table_name` 和 `db_name.table_name`
- `PRINT_MODEL_OUTPUT=true` 时，会流式打印模型输出、工具调用和工具结果
- 不配置 `MYSQL_DATABASE` 也可以运行，agent 会自行探索 `information_schema`

## 行为说明

这个 agent 的调用方式与 LangChain 文档中的 `create_agent` 一致：

```python
result = agent.invoke(
    {"messages": [{"role": "user", "content": "analytics 库里有哪些表"}]}
)
```

CLI 在交互模式下会维护完整 `messages` 历史，因此可以连续追问，比如：

- `当前实例有哪些数据库`
- `analytics 库里有哪些表`
- `再看 users 表结构`
- `统计这个表最近 7 天新增数据`

## 注意事项

- 默认只允许单条 `SELECT` / `WITH` 查询，避免误执行增删改
- 如果要放开写操作，需要显式设置 `ALLOW_WRITE=true`
- 为了减少歧义，SQL 中尽量显式使用 `db_name.table_name`
- 当前依赖 `langchain`、`langchain-openai`、`pymysql`、`python-dotenv`
