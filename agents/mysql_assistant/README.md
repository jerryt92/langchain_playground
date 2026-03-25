# mysql_assistant

`mysql_assistant` 是一个基于大模型的 MySQL 自然语言查询助手。

它现在是一个 `tool use` 模式的智能体：

- 每次提问时，模型会根据需要反复调用工具
- 工具包括列库、列表、看表结构、执行 SQL
- 在交互模式下会保留会话上下文，后续问题会继承前文

和旧版不同的是，它不再是“一次性生成 SQL 再执行”的单轮流程；只要能连上 MySQL 实例，就可以在运行时探索数据库、表和字段。

## 模块结构

- `mysql_assistant.py`：负责读取配置、组装依赖和提供 CLI 入口
- `mysql_ops.py`：负责 MySQL 连接、元数据查询、SQL 安全校验和执行
- `chat.py`：负责模型、工具注册、tool use 循环和上下文历史

## 入口

标准入口：

```bash
python agents/mysql_assistant/main.py
```

也可以通过根运行器启动：

```bash
python main.py
```

## 环境变量

这个 agent 使用“公共配置 + agent 配置”两层环境变量：

- 项目根目录 `.env`：放模型配置
- `agents/mysql_assistant/.env`：放数据库配置

参考示例：

- 根配置：`.env.example`
- agent 配置：`agents/mysql_assistant/.env.example`

### 根 `.env`

推荐放这些通用模型变量：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`（可选）
- `OPENAI_MODEL`（可选，默认 `gpt-4o-mini`）

### `agents/mysql_assistant/.env`

数据库相关变量：

- `MYSQL_URI`（可选，保留兼容）
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DATABASE`（可选，不填表示启动时不预选默认库）
- `ALLOW_WRITE`（可选，默认 `false`）
- `INCLUDE_TABLES`（可选）
- `PRINT_MODEL_OUTPUT`（可选，默认 `false`，开启后打印模型输出和工具调用轨迹）

推荐优先使用分字段配置：

```bash
MYSQL_HOST=172.17.64.106
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD='Raisecom3##'
# MYSQL_DATABASE=your_database_name
ALLOW_WRITE=false
INCLUDE_TABLES=
PRINT_MODEL_OUTPUT=false
```

说明：

- 如果未设置 `MYSQL_URI`，程序会自动用 `MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DATABASE` 拼出连接串
- 不带库名也可以正常启动，agent 会自行查询 `information_schema`
- 如果连接串里带了默认库，agent 也不会依赖它，而是优先生成带库名前缀的 SQL
- `INCLUDE_TABLES` 支持 `table_name` 或 `db_name.table_name` 两种写法
- `PRINT_MODEL_OUTPUT=true` 时，会打印模型输出、工具参数和工具结果，便于排查 agent 的决策过程

同时也兼容以下 `MYSQL_URI` 写法：

```bash
MYSQL_URI=mysql+pymysql://user:password@127.0.0.1:3306
MYSQL_URI=mysql+pymysql://user:password@127.0.0.1:3306/your_db
MYSQL_URI=jdbc:mysql://127.0.0.1:3306
```

## 变量优先级

如果出现同名变量，覆盖顺序是：

1. 进程环境变量
2. `agents/mysql_assistant/.env`
3. 项目根目录 `.env`

也就是说，agent 自己的 `.env` 会覆盖根 `.env` 里的同名变量。

## 使用示例

单次提问：

```bash
python agents/mysql_assistant/main.py "当前实例有哪些数据库"
```

交互模式：

```bash
python agents/mysql_assistant/main.py
```

输入 `exit`、`quit` 或 `q` 可以退出。

输入 `clear` 或 `reset` 可以清空当前会话上下文。

示例提问：

- `当前实例有哪些数据库`
- `analytics 库里有哪些表`
- `统计 crm.users 表中的用户总数`
- `统计 sales.orders 最近 30 天订单数`

## Agent 行为

- 模型会优先调用元数据工具，再决定是否执行 SQL
- 如果问题信息不足，模型会继续调工具，而不是直接猜库名或字段名
- 交互模式下会保留历史消息，因此可以连续追问，比如“再看这个表最近 7 天的数据”

## 注意事项

- 默认只允许单条 `SELECT` / `WITH` 查询，避免误执行增删改
- 如果要放开写操作，需要显式设置 `ALLOW_WRITE=true`
- 只读模式下，`run_sql` 工具会拒绝非 `SELECT` / `WITH` 语句
- 为了避免歧义，执行 SQL 时应尽量显式使用 `db_name.table_name`
- 当前运行依赖 `langchain`、`langchain-openai`、`pymysql`、`python-dotenv`
