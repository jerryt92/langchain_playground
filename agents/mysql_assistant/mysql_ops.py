import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import pymysql

WRITE_SQL_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|REPLACE|UPSERT|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|MERGE|CALL|USE|SET|OUTFILE|DUMPFILE|LOCK|UNLOCK)\b|LOAD\s+DATA",
    flags=re.IGNORECASE,
)
READONLY_SQL_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", flags=re.IGNORECASE)
DEFAULT_MAX_RESULT_ROWS = 200


@dataclass
class ConnectionConfig:
    host: str
    port: int
    user: str
    password: str
    database: Optional[str]
    charset: str
    connect_timeout: int
    read_timeout: Optional[int]
    write_timeout: Optional[int]


def _strip_wrapping_quotes(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _get_first_query_value(query_params: dict[str, list[str]], key: str) -> Optional[str]:
    values = query_params.get(key)
    if not values:
        return None
    return values[0]


def _parse_optional_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().strip("`").lower()


def _clean_identifier(identifier: str) -> str:
    text = identifier.strip().strip("`")
    if not text:
        raise ValueError("标识符不能为空。")
    return text


def build_mysql_uri_from_env(env: Mapping[str, str]) -> str:
    """兼容使用 MYSQL_HOST/MYSQL_PORT/MYSQL_USER 等分字段配置连接信息。"""
    host = _strip_wrapping_quotes(env.get("MYSQL_HOST")) or "127.0.0.1"
    port = _strip_wrapping_quotes(env.get("MYSQL_PORT")) or "3306"
    user = _strip_wrapping_quotes(env.get("MYSQL_USER"))
    password = _strip_wrapping_quotes(env.get("MYSQL_PASSWORD")) or ""
    database = _strip_wrapping_quotes(env.get("MYSQL_DATABASE")) or ""

    if not user:
        raise ValueError(
            "缺少环境变量 MYSQL_URI，且未提供 MYSQL_USER。"
            "请配置 MYSQL_URI，或使用 MYSQL_HOST/MYSQL_PORT/MYSQL_USER/MYSQL_PASSWORD。"
        )

    user_enc = quote_plus(user)
    pwd_enc = quote_plus(password)
    db_path = f"/{quote_plus(database)}" if database else ""
    return f"mysql+pymysql://{user_enc}:{pwd_enc}@{host}:{port}{db_path}"


def normalize_mysql_uri(raw_uri: str, env: Mapping[str, str]) -> str:
    """把多种 MySQL 连接串规范成 pymysql 可直接消费的 URI。"""
    uri = raw_uri.strip()
    if not uri:
        return build_mysql_uri_from_env(env)

    if uri.startswith("mysql+pymysql://"):
        return uri

    if uri.startswith("mysql://"):
        return "mysql+pymysql://" + uri[len("mysql://") :]

    if uri.startswith("jdbc:mysql://"):
        jdbc_uri = uri[len("jdbc:") :]
        parsed = urlparse(jdbc_uri)

        user = _strip_wrapping_quotes(env.get("MYSQL_USER"))
        password = _strip_wrapping_quotes(env.get("MYSQL_PASSWORD")) or ""
        if not user:
            raise ValueError("使用 JDBC URL 时需要设置 MYSQL_USER。")

        db_name = parsed.path.lstrip("/") or _strip_wrapping_quotes(env.get("MYSQL_DATABASE")) or ""
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 3306
        path = f"/{db_name}" if db_name else ""
        query = f"?{parsed.query}" if parsed.query else ""
        user_enc = quote_plus(user)
        pwd_enc = quote_plus(password)
        return f"mysql+pymysql://{user_enc}:{pwd_enc}@{host}:{port}{path}{query}"

    raise ValueError(
        "MYSQL_URI 格式不支持。请使用 mysql+pymysql://...、mysql://... 或 jdbc:mysql://..."
    )


def parse_connection_config(mysql_uri: str) -> ConnectionConfig:
    """把 URI 拆成直接连接 pymysql 所需的参数。"""
    parsed = urlparse(mysql_uri)
    if parsed.scheme != "mysql+pymysql":
        raise ValueError("MYSQL_URI 必须使用 mysql+pymysql:// 协议。")

    if not parsed.username:
        raise ValueError("MYSQL_URI 缺少用户名。")

    query_params = parse_qs(parsed.query, keep_blank_values=True)
    charset = _get_first_query_value(query_params, "charset") or "utf8mb4"
    connect_timeout = int(_get_first_query_value(query_params, "connect_timeout") or 10)
    read_timeout = _parse_optional_int(_get_first_query_value(query_params, "read_timeout"))
    write_timeout = _parse_optional_int(_get_first_query_value(query_params, "write_timeout"))

    return ConnectionConfig(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=unquote(parsed.username),
        password=unquote(parsed.password or ""),
        database=parsed.path.lstrip("/") or None,
        charset=charset,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        write_timeout=write_timeout,
    )


def normalize_sql(raw_sql: str) -> str:
    sql = raw_sql.strip()

    if sql.startswith("```"):
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE).strip()
        sql = re.sub(r"\s*```$", "", sql).strip()

    if "SQLQuery:" in sql:
        sql = sql.split("SQLQuery:", 1)[1].strip()
    if "SQLResult:" in sql:
        sql = sql.split("SQLResult:", 1)[0].strip()
    if "Answer:" in sql:
        sql = sql.split("Answer:", 1)[0].strip()

    if ";" in sql:
        parts = [part.strip() for part in sql.split(";") if part.strip()]
        if len(parts) != 1:
            raise ValueError("仅允许单条 SQL 语句，检测到多语句。")
        sql = parts[0]

    return sql


def enforce_policy(sql: str, allow_write: bool) -> None:
    if ";" in sql:
        raise PermissionError("仅允许执行单条 SQL 语句。")

    if allow_write:
        return

    if not READONLY_SQL_PATTERN.match(sql):
        raise PermissionError("当前为只读模式，仅允许 SELECT 或 WITH 查询。")
    if WRITE_SQL_PATTERN.search(sql):
        raise PermissionError("检测到写操作或危险关键字，已拒绝执行。")


def serialize_tool_result(result: dict[str, Any]) -> str:
    if "affected_rows" in result:
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)

    rows = result.get("rows", [])
    payload: dict[str, Any] = {"row_count": len(rows), "rows": rows[:DEFAULT_MAX_RESULT_ROWS]}
    if len(rows) > DEFAULT_MAX_RESULT_ROWS:
        payload["truncated"] = True
        payload["preview_rows"] = DEFAULT_MAX_RESULT_ROWS
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


class MySQLOps:
    """封装 MySQL 连接、元数据探索和 SQL 执行策略。"""

    def __init__(self, mysql_uri: str, allow_write: bool = False, include_tables: Optional[list[str]] = None):
        self.mysql_uri = mysql_uri
        self.allow_write = allow_write
        self.include_tables = include_tables or []
        self.connection_config = parse_connection_config(mysql_uri)

    def _connect(self, database: Optional[str] = None) -> pymysql.connections.Connection:
        """默认不选库连接，避免运行时依赖 USE db 的会话状态。"""
        return pymysql.connect(
            host=self.connection_config.host,
            port=self.connection_config.port,
            user=self.connection_config.user,
            password=self.connection_config.password,
            database=database,
            charset=self.connection_config.charset,
            connect_timeout=self.connection_config.connect_timeout,
            read_timeout=self.connection_config.read_timeout,
            write_timeout=self.connection_config.write_timeout,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )

    def _fetch_all(
        self,
        sql: str,
        params: Optional[tuple[Any, ...]] = None,
        database: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        connection = self._connect(database=database)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params or ())
                return list(cursor.fetchall())
        finally:
            connection.close()

    def execute_sql(self, sql: str) -> dict[str, Any]:
        """执行单条 SQL；查询返回行数据，写操作返回影响行数。"""
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                if cursor.description:
                    return {"rows": list(cursor.fetchall())}
                return {"affected_rows": cursor.rowcount}
        finally:
            connection.close()

    def run_sql(self, sql: str) -> str:
        normalized_sql = normalize_sql(sql)
        enforce_policy(normalized_sql, allow_write=self.allow_write)
        result = self.execute_sql(normalized_sql)
        return serialize_tool_result(result)

    def list_databases(self) -> list[str]:
        rows = self._fetch_all(
            """
            SELECT schema_name AS schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            ORDER BY schema_name
            """
        )
        return [str(row["schema_name"]) for row in rows]

    def _table_allowed(self, database_name: str, table_name: str) -> bool:
        """兼容 `table` 和 `db.table` 两种 INCLUDE_TABLES 写法。"""
        if not self.include_tables:
            return True

        target_db = _normalize_identifier(database_name)
        target_table = _normalize_identifier(table_name)

        for item in self.include_tables:
            normalized = _normalize_identifier(item)
            if "." in normalized:
                item_db, item_table = normalized.split(".", 1)
                if item_db == target_db and item_table == target_table:
                    return True
                continue
            if normalized == target_table:
                return True
        return False

    def list_tables(self, database_name: str) -> list[dict[str, str]]:
        database_name = _clean_identifier(database_name)
        rows = self._fetch_all(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY table_name
            """,
            params=(database_name,),
        )
        return [
            {"table_name": str(row["table_name"]), "table_type": str(row["table_type"])}
            for row in rows
            if self._table_allowed(database_name, str(row["table_name"]))
        ]

    def get_table_schema(self, database_name: str, table_name: str) -> dict[str, Any]:
        database_name = _clean_identifier(database_name)
        table_name = _clean_identifier(table_name)
        if not self._table_allowed(database_name, table_name):
            raise PermissionError(f"表 `{database_name}.{table_name}` 不在 INCLUDE_TABLES 允许范围内。")

        rows = self._fetch_all(
            """
            SELECT
                column_name,
                data_type,
                column_type,
                is_nullable,
                column_key,
                column_default,
                extra,
                column_comment
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            params=(database_name, table_name),
        )
        if not rows:
            raise ValueError(f"未找到表 `{database_name}.{table_name}`。")
        return {
            "database_name": database_name,
            "table_name": table_name,
            "columns": rows,
        }
