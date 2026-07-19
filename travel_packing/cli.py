from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from langgraph.types import Command

from .graph import build_graph
from .render import render_console
from .state import initial_state


def _create_checkpointer(sqlite_path: str | None):
    if not sqlite_path:
        return None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise SystemExit(
            "使用 --sqlite 需要先安装 langgraph-checkpoint-sqlite："
            "python -m pip install langgraph-checkpoint-sqlite"
        ) from exc
    path = Path(sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    return SqliteSaver(connection)


def _run_until_ready(graph, value, config):
    result = graph.invoke(value, config=config)
    while result.get("__interrupt__"):
        interrupt_data = result["__interrupt__"][0].value
        print("\n需要你的补充：" + interrupt_data.get("message", str(interrupt_data)))
        answer = input("> ").strip()
        result = graph.invoke(Command(resume=answer), config=config)
    return result


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="LangGraph 智能旅行打包助手")
    parser.add_argument("trip", nargs="?", help="初始行程描述")
    parser.add_argument("--thread-id", default=str(uuid4()), help="持久化会话 ID")
    parser.add_argument("--sqlite", help="可选：SQLite 检查点文件，用于跨进程持久化")
    parser.add_argument("--update", action="store_true", help="将本次输入作为已有 thread-id 的追加信息")
    args = parser.parse_args()

    trip = args.trip or input("请描述你的行程：\n> ").strip()
    graph = build_graph(checkpointer=_create_checkpointer(args.sqlite))
    config = {"configurable": {"thread_id": args.thread_id}}
    graph_input = {"raw_input": trip, "is_update": True} if args.update else initial_state(trip)
    result = _run_until_ready(graph, graph_input, config)
    print("\n" + render_console(result))

    while True:
        update = input("\n追加信息（输入 q 退出）：\n> ").strip()
        if update.lower() in {"q", "quit", "exit"}:
            break
        result = _run_until_ready(
            graph,
            {"raw_input": update, "is_update": True},
            config,
        )
        print("\n" + render_console(result))


if __name__ == "__main__":
    main()
