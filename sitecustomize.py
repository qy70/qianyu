"""只在本项目启动的 Python 中激活独立依赖及 Windows 扩展的标准 .pth。"""

from pathlib import Path

import site
import os
import sys

_dependencies = Path(__file__).resolve().parent / ".runtime" / "site-packages"
if _dependencies.is_dir():
    site.addsitedir(str(_dependencies))

# 仅为本发行版启动的 MaiBot Worker 提供正常关停信号，不改上游代码。
if (os.environ.get("MAIBOT_WORKER_PROCESS") == "1"
        and os.environ.get("FATFISH_STOP_FILE")
        and "src.runtime" in sys.orig_argv):
    import _thread
    import threading
    import time

    def _watch_stop_request():
        marker = Path(os.environ["FATFISH_STOP_FILE"])
        while True:
            time.sleep(0.5)
            if marker.exists():
                _thread.interrupt_main()
                return

    threading.Thread(target=_watch_stop_request, name="fatfish-shutdown", daemon=True).start()
