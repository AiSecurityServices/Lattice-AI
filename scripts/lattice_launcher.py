"""Lattice AI 最小启动器。

双击（或通过桌面快捷方式）运行：启动本地服务（同源托管 API 与 Web UI），
等待健康检查通过后自动打开浏览器。控制台会显示服务日志，按 Ctrl+C 或
关闭窗口停止服务。

用法：
    python scripts/lattice_launcher.py [--port 8742] [--no-browser]

服务已在本端口运行时，只打开浏览器，不会重复启动。
"""
import argparse
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DEFAULT_PORT = 8742


def server_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def is_alive(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Lattice AI 本地启动器")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="只启动服务，不打开浏览器")
    args = parser.parse_args()
    port = args.port
    url = server_url(port)

    if is_alive(port):
        print(f"[lattice] 服务已在运行：{url}")
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    try:
        import uvicorn
        from lattice_ai import runtime
        from lattice_ai.server import app
    except Exception as exc:
        print(f"[lattice] 启动失败，依赖未就绪：{exc}")
        print("请先在项目目录执行: pip install -e .[dev]  并完成前端构建 (cd web && npm run build)")
        return 1

    print(f"[lattice] 正在启动服务（端口 {port}）...")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 20
    while time.time() < deadline:
        if is_alive(port, timeout=0.5):
            break
        if not thread.is_alive():
            print("[lattice] 服务线程已退出，启动失败（请查看上方日志）")
            return 1
        time.sleep(0.25)
    else:
        print("[lattice] 等待服务超时，启动失败（请查看上方日志）")
        return 1

    print()
    print("=" * 56)
    print(f"  Lattice AI 已就绪: {url}")
    print(f"  数据目录: {runtime._DATA_ROOT}")
    print("  停止服务: 按 Ctrl+C 或关闭本窗口")
    print("=" * 56)
    print()
    if not args.no_browser:
        webbrowser.open(url)

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print("[lattice] 正在停止服务...")
    server.should_exit = True
    thread.join(timeout=5)
    print("[lattice] 已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
