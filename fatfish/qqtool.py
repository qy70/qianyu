"""管理官方独立 Node 组件；账号、认证与写入目录都属于个人实例。"""

from pathlib import Path
import base64
import hashlib
import io
import json
import os
import secrets
import socket
import subprocess
import threading
import time
import zipfile

from fatfish.core import atomic_text, read_json, tcp_open

VERSION = "v4.18.42"
ASSET = "NapCat.Shell.Windows.Node.zip"
URL = f"https://github.com/NapNeko/NapCatQQ/releases/download/{VERSION}/{ASSET}"
# 从上述官方 HTTPS 固定版本资产下载并计算，不使用可变的 latest 链接。
SHA256 = "77397ac38d66f46383e48f08f35d5f9d37ec575c22069f62d6c600e73b4521ed"
REQUIRED = ("node.exe", "index.js", "wrapper.node", "napcat/napcat.mjs")


def extract_checked(archive_path, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive_path) as archive:
        total = 0
        for entry in archive.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination) or "\\" in entry.filename or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("组件压缩包包含无效路径")
            total += entry.file_size
            if total > 1500 * 1024 * 1024:
                raise ValueError("组件解压大小异常")
        archive.extractall(destination)


class OwnedProcess:
    """Windows Job 句柄只管理本应用创建的子进程，不按进程名关 QQ。"""
    def __init__(self, args, **kwargs):
        self.job = None
        self.process = None
        if os.name == "nt":
            import win32job
            self.job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
        try:
            kwargs.setdefault("stdout", subprocess.DEVNULL)
            kwargs.setdefault("stderr", subprocess.DEVNULL)
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0, **kwargs)
            if self.job:
                win32job.AssignProcessToJobObject(self.job, self.process._handle)
        except Exception:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
            if self.job:
                self.job.Close()
            raise

    def poll(self):
        return self.process.poll()

    def close(self):
        if self.job:
            self.job.Close()
            self.job = None
        elif self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=15)


class QQTool:
    def __init__(self, manager):
        self.manager = manager
        self.root = manager.root
        self.binary = self.root / ".external" / ("NapCat-" + VERSION)
        self.home = manager.instance / "qq"
        self.work = self.home / "napcat"
        self.lock = threading.RLock()
        self.api_lock = threading.RLock()
        self.cancel = threading.Event()
        self.process = None
        self.thread = None
        self.credential = ""
        self.credential_time = 0
        self.port = None
        self.web_token = ""
        self.qr_source = ""
        self.output = None
        self.state = {"phase": "stopped" if self.installed() else "missing", "message": "打开桌面版时会自动准备并启动 QQ 组件", "qr": "", "account": "", "progress": 0}

    def installed(self):
        return all((self.binary / p).is_file() for p in REQUIRED)

    def snapshot(self):
        with self.lock:
            return {**self.state, "installed": self.installed(), "version": VERSION,
                    "running": bool(self.process and self.process.poll() is None)}

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def ensure(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return {"message": "QQ 组件正在运行或准备，请查看登录状态"}
            self.cancel.clear()
            self.update(phase="preparing", message="正在准备 QQ 组件……", qr="", account="")
            self.thread = threading.Thread(target=self._run, daemon=True, name="fatfish-qq")
            self.thread.start()
        return {"message": "已开始准备 QQ 组件，首次需要联网下载约 119 MB"}

    def _install(self):
        if self.installed():
            return
        import httpx
        cache = self.root / ".external" / "downloads" / (VERSION + "-" + ASSET)
        cache.parent.mkdir(parents=True, exist_ok=True)
        valid_cache = False
        if cache.exists():
            with cache.open("rb") as handle:
                valid_cache = hashlib.file_digest(handle, "sha256").hexdigest() == SHA256
        if not valid_cache:
            part = cache.with_suffix(".partial")
            self.update(phase="downloading", message="正在从 NapCat 官方下载独立 QQ 组件……", progress=0)
            started = time.monotonic()
            try:
                with httpx.Client(follow_redirects=True, timeout=30, trust_env=False) as client:
                    with client.stream("GET", URL) as response:
                        response.raise_for_status()
                        size = int(response.headers.get("Content-Length", 0))
                        count = 0
                        with part.open("wb") as handle:
                            for chunk in response.iter_bytes(1024 * 256):
                                if self.cancel.is_set():
                                    raise InterruptedError("已取消组件准备")
                                if time.monotonic() - started > 600:
                                    raise TimeoutError("组件下载超过十分钟，请检查网络后重试")
                                count += len(chunk)
                                if count > 300 * 1024 * 1024:
                                    raise ValueError("下载大小异常")
                                handle.write(chunk)
                                self.update(progress=min(99, int(count * 100 / size)) if size else 0)
                with part.open("rb") as handle:
                    if hashlib.file_digest(handle, "sha256").hexdigest() != SHA256:
                        raise ValueError("官方组件校验失败，未运行下载内容")
                part.replace(cache)
            finally:
                part.unlink(missing_ok=True)
        if self.cancel.is_set():
            raise InterruptedError("已取消组件准备")
        self.update(phase="extracting", message="下载已校验，正在解压独立组件……", progress=100)
        extract_checked(cache, self.binary)
        if not self.installed():
            raise ValueError("官方组件目录不完整，请重新下载")
        license_path = self.root / "templates" / "NapCat-LICENSE.txt"
        if license_path.exists():
            atomic_text(self.binary / "NapCat-LICENSE.txt", license_path.read_text(encoding="utf-8"))
        atomic_text(self.binary / "Fatfish-source.txt", f"Unmodified official asset: {URL}\nSHA256: {SHA256}\nNapCat copyright 2024 Mlikiowa; subject to NapCat Limited Redistribution License.\nQQ components remain subject to Tencent terms.\n")

    def _configure(self):
        settings = self.manager.settings(private=True)
        if tcp_open(settings["qq_host"], settings["qq_port"]):
            raise ValueError("QQ 消息接口端口已被占用。请停止旧的接入组件，或保存一个空闲端口后重试")
        self.home.mkdir(parents=True, exist_ok=True)
        state = read_json(self.home / "local.json", {})
        self.web_token = state.get("token") or secrets.token_urlsafe(32)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        atomic_text(self.home / "local.json", json.dumps({"token": self.web_token, "port": self.port}))
        config = self.work / "config"
        atomic_text(config / "webui.json", json.dumps({"host": "127.0.0.1", "port": self.port, "prefix": "", "token": self.web_token, "loginRate": 10}))
        onebot = {"network": {"websocketServers": [{"name": "fatfish", "enable": True, "host": "127.0.0.1", "port": settings["qq_port"], "token": settings["qq_token"], "messagePostFormat": "array", "reportSelfMessage": False}]}}
        atomic_text(config / "onebot11.json", json.dumps(onebot))
        # 只为用户明确填写的小号更新本应用实例配置。
        if settings["qq_account"]:
            atomic_text(config / f"onebot11_{settings['qq_account']}.json", json.dumps(onebot))
        (self.home / "data").mkdir(exist_ok=True)
        env = os.environ.copy()
        for name in tuple(env):
            if name.startswith("NAPCAT_"):
                env.pop(name)
        env.update(NAPCAT_WORKDIR=str(self.work), NAPCAT_QQ_DATA_DIR=str(self.home / "data"), NAPCAT_WEBUI_PREFERRED_PORT=str(self.port))
        if settings["qq_account"]:
            env["NAPCAT_QUICK_ACCOUNT"] = settings["qq_account"]
        self.credential = ""
        self.credential_time = 0
        self.qr_source = ""
        return env

    def _api(self, path, data=None):
        with self.api_lock:
            return self._api_locked(path, data)

    def _api_locked(self, path, data=None):
        import httpx
        def request(route, body, credential=""):
            response = httpx.post(f"http://127.0.0.1:{self.port}/api/{route}", json=body or {},
                                  headers={"Authorization": "Bearer " + credential} if credential else {}, timeout=5, trust_env=False)
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                raise ValueError("QQ 本机接口：" + str(result.get("message", "未返回结果")))
            return result.get("data") or {}
        if not self.credential or time.monotonic() - self.credential_time > 3000:
            digest = hashlib.sha256((self.web_token + ".napcat").encode()).hexdigest()
            self.credential = request("auth/login", {"hash": digest})["Credential"]
            self.credential_time = time.monotonic()
        return request(path, data, self.credential)

    def _poll(self):
        info = self._api("QQLogin/CheckLoginStatus")
        if info.get("isLogin"):
            account = str(self._api("QQLogin/GetQQLoginInfo").get("uin", ""))
            expected = self.manager.settings()["qq_account"]
            if expected and expected != account:
                self.update(phase="mismatch", account=account, qr="", message="登录账号与连接设置不一致，请核对后再启动核心")
            else:
                self.update(phase="online", account=account, qr="", message="QQ 小号已登录。填写 API 和聊天范围后可启动大肥鱼")
            return
        source = info.get("qrcodeurl", "")
        qr = self.state["qr"]
        if source and source != self.qr_source:
            import qrcode
            from qrcode.image.svg import SvgPathImage
            if not isinstance(source, str) or len(source) > 4096:
                raise ValueError("二维码内容无效")
            image = qrcode.make(source, image_factory=SvgPathImage, border=4)
            stream = io.BytesIO()
            image.save(stream)
            qr = "data:image/svg+xml;base64," + base64.b64encode(stream.getvalue()).decode()
            self.qr_source = source
        phase = "confirming" if info.get("loginPhase") in {"qrcode_scanned", "initializing", "reconnecting"} else "waiting_qr"
        message = "请在手机 QQ 上确认登录，正在等待组件就绪" if phase == "confirming" else "请用专门的小号扫描二维码，并在手机上确认登录"
        if info.get("loginError"):
            message = "QQ 登录提示：" + str(info["loginError"])[:240]
        self.update(phase=phase, message=message, qr=qr, account="")

    def _run(self):
        import httpx
        try:
            self._install()
            if self.cancel.is_set():
                return
            env = self._configure()
            self.update(phase="starting", message="正在启动独立 QQ 登录服务……", qr="")
            with self.lock:
                if self.cancel.is_set():
                    return
                self.output = (self.home / "launcher.log").open("wb")
                self.process = OwnedProcess([str(self.binary / "node.exe"), str(self.binary / "index.js")], cwd=self.binary, env=env,
                                            stdout=self.output, stderr=subprocess.STDOUT)
            failures = 0
            while not self.cancel.is_set():
                if self.process.poll() is not None:
                    raise ValueError(f"QQ 组件已退出（{self.process.poll()}）。可检查 {self.work / 'logs'} 后重试")
                try:
                    self._poll()
                    failures = 0
                except (httpx.HTTPError, ValueError, KeyError) as error:
                    failures += 1
                    if failures >= 20:
                        raise ValueError("QQ 登录服务连续一分钟未就绪，请检查网络或组件日志后重试") from error
                    if failures >= 2:
                        self.update(phase="starting", qr="", message="正在等待 QQ 本机登录服务响应……")
                self.cancel.wait(3)
        except Exception as error:
            if not self.cancel.is_set():
                self.update(phase="error", message=self.manager.redact(str(error)), qr="")
        finally:
            with self.lock:
                if self.process:
                    self.process.close()
                    self.process = None
                if self.output:
                    self.output.close()
                    self.output = None

    def refresh_qr(self):
        if not self.process or self.process.poll() is not None:
            raise ValueError("请先启动 QQ 组件")
        self._api("QQLogin/RefreshQRcode")
        self.qr_source = ""
        return {"message": "已请求刷新二维码，请稍候"}

    def stop(self):
        self.cancel.set()
        thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=16)
        with self.lock:
            if self.process:
                self.process.close()
                self.process = None
            if self.output:
                self.output.close()
                self.output = None
        self.update(phase="stopped", qr="", account="", message="QQ 组件已停止，登录资料保留在个人实例")
        return {"message": "已停止本应用启动的 QQ 组件"}
