"""一键启动网页版旅行小助手。

运行方式：
    python agent_web.py

脚本会自动：
1. 检查 streamlit 是否已安装（缺失则提示安装命令）
2. 在后台启动 streamlit 服务（默认端口 8501）
3. 等待服务就绪后自动打开默认浏览器访问 http://localhost:8501/
4. 在终端按 Ctrl+C 即可关闭服务
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from dotenv import load_dotenv

from travel_packing.services import DeepSeekConfigurationError, require_deepseek_api_key

HOST = "localhost"
PORT = 8501
APP_FILE = Path(__file__).resolve().parent / "app.py"
URL = f"http://{HOST}:{PORT}/"


def _find_streamlit_python() -> str | None:
    """返回能够 import streamlit 的 Python 解释器路径。

    优先使用当前解释器，其次尝试项目内的 .venv，最后尝试系统 python。
    """
    candidates: list[str] = []
    # 1. 当前解释器
    candidates.append(sys.executable)
    # 2. 项目内的 .venv（Windows 布局）
    venv_python = Path(__file__).resolve().parent / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        candidates.append(str(venv_python))
    # 3. 系统 python（仅当与当前不同时）
    if sys.executable.lower() != sys.prefix.lower():
        candidates.append(sys.prefix + "\\python.exe")

    seen: set[str] = set()
    for python in candidates:
        python = os.path.normpath(python)
        if python in seen or not Path(python).exists():
            continue
        seen.add(python)
        try:
            result = subprocess.run(
                [python, "-c", "import streamlit"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                return python
        except (subprocess.SubprocessError, OSError):
            continue
    return None


def _wait_for_server(timeout: float = 30.0) -> bool:
    """轮询 URL 直到服务响应或超时。"""
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def _open_browser_later(delay: float = 1.5) -> None:
    """延迟打开浏览器，给 streamlit 一点启动时间。"""

    def _open() -> None:
        time.sleep(delay)
        webbrowser.open(URL)

    threading.Thread(target=_open, daemon=True).start()


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    try:
        require_deepseek_api_key()
    except DeepSeekConfigurationError as exc:
        print(f"[错误] {exc}")
        return 1

    if not APP_FILE.exists():
        print(f"[错误] 找不到应用文件：{APP_FILE}")
        return 1

    python = _find_streamlit_python()
    if python is None:
        print("[错误] 未找到可用的 Python 解释器，或未安装 streamlit。")
        print("请先执行：python -m pip install -r requirements.txt")
        return 1

    print(f"[信息] 使用 Python：{python}")
    print(f"[信息] 启动 Streamlit 应用：{APP_FILE.name}")
    print(f"[信息] 访问地址：{URL}")
    print("[信息] 在浏览器中即可使用「旅行小助手」。按 Ctrl+C 可停止服务。")
    print()

    # 启动后自动打开浏览器
    _open_browser_later()

    # 以 headless=false 让 streamlit 不自动打开自己的浏览器（避免重复）
    # 这里我们用 --server.headless=true，由本脚本统一控制浏览器打开时机
    cmd = [
        python,
        "-m",
        "streamlit",
        "run",
        str(APP_FILE),
        "--server.headless=true",
        "--server.port",
        str(PORT),
        "--server.address",
        HOST,
        "--browser.gatherUsageStats=false",
    ]

    try:
        proc = subprocess.run(cmd)
        return proc.returncode
    except KeyboardInterrupt:
        print("\n[信息] 已停止服务。")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
