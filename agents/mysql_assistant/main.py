import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


if __name__ == "__main__":
    print("正在初始化 mysql_assistant，请稍候...", flush=True)
    from chat_cli import main

    raise SystemExit(main())
