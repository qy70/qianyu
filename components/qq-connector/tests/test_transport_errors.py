"""连接失败的原因提示和访问令牌脱敏回归测试。"""

from aiohttp import ClientConnectorError, ClientSSLError, RequestInfo, WSServerHandshakeError
from aiohttp.client_reqrep import ConnectionKey
from importlib import import_module
from multidict import CIMultiDict, CIMultiDictProxy
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote, quote_plus
from yarl import URL

import errno
import pytest
import socket


transport = import_module("plugins.MaiBot-SnowLuma-Adapter-main.transport")
config = import_module("plugins.MaiBot-SnowLuma-Adapter-main.config")
CONNECTION_KEY = ConnectionKey("127.0.0.1", 3001, False, True, None, None, None)
TOKEN = "private token/+?=&"


def handshake_error(status: int, token: str = TOKEN) -> WSServerHandshakeError:
    url = URL("ws://127.0.0.1:3001/").with_query(access_token=token)
    request = RequestInfo(url, "GET", CIMultiDictProxy(CIMultiDict()), url)
    return WSServerHandshakeError(request, (), status=status, message="Invalid response status")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "token", "expected"),
    [
        (handshake_error(401), TOKEN, "client.token 已配置但未通过校验"),
        (handshake_error(401, ""), "", "当前未配置 client.token"),
        (handshake_error(403), TOKEN, "访问被拒绝（HTTP 403）"),
        (handshake_error(404), TOKEN, "接口不存在（HTTP 404）"),
        (handshake_error(200), TOKEN, "WebSocket 握手失败（HTTP 200）"),
        (handshake_error(502), TOKEN, "WebSocket 握手失败（HTTP 502）"),
        (
            ClientConnectorError(CONNECTION_KEY, ConnectionRefusedError(errno.ECONNREFUSED, "refused")),
            "",
            "目标端口拒绝连接",
        ),
        (ClientConnectorError(CONNECTION_KEY, OSError(10061, "refused")), TOKEN, "目标端口拒绝连接"),
        (ClientConnectorError(CONNECTION_KEY, socket.gaierror(-2, "unknown host")), TOKEN, "域名解析失败"),
        (ClientConnectorError(CONNECTION_KEY, OSError(errno.ENETUNREACH, "unreachable")), TOKEN, "无法建立网络连接"),
        (ClientSSLError(CONNECTION_KEY, OSError("certificate invalid")), TOKEN, "TLS 握手或证书校验失败"),
        (TimeoutError(), TOKEN, "连接或通信超时"),
        (RuntimeError(f"unexpected {TOKEN} {quote(TOKEN, safe='')} {quote_plus(TOKEN)}"), TOKEN, "连接或通信发生异常"),
    ],
)
async def test_connection_loop_logs_actionable_reason_without_token(monkeypatch, error, token, expected):
    logger = Mock()
    client = transport.QQTransportClient(logger, AsyncMock(), AsyncMock(), AsyncMock())
    client.configure(config.QQServerConfig(token=token))
    session = Mock()
    session.__aenter__ = AsyncMock(side_effect=error)
    session.__aexit__ = AsyncMock()
    monkeypatch.setattr(transport, "ClientSession", Mock(return_value=session))

    # 在一次真实异常处理后退出循环，验证最终日志而不连接用户的运行实例。
    def stop_after_failure(message):
        if "连接失败:" in message:
            client._stop_requested = True

    logger.warning.side_effect = stop_after_failure
    await client._connection_loop()

    message = logger.warning.call_args.args[0]
    assert expected in message
    assert "ws://127.0.0.1:3001" in message
    assert "原始错误" not in message
    assert type(error).__name__ not in message
    if expected == "目标端口拒绝连接":
        assert "Token 校验阶段" not in message
        assert "且 client.server、client.port 与 地址 和 端口 一致；将在" in message
    assert "将在 5 秒后重连" in message
    for secret in (TOKEN, quote(TOKEN, safe=""), quote_plus(TOKEN)):
        assert secret not in message
    if isinstance(error, ClientConnectorError):
        assert "请补全 token" not in message


def test_disconnect_reason_redacts_token_in_exception_url():
    logger = Mock()
    client = transport.QQTransportClient(logger, AsyncMock(), AsyncMock(), AsyncMock())
    server_config = config.QQServerConfig(token=TOKEN)
    client._log_connection_closed(
        client._build_display_url(server_config), server_config, str(handshake_error(401))
    )
    message = logger.warning.call_args.args[0]
    assert "401" in message
    assert TOKEN not in message
    assert quote_plus(TOKEN) not in message
    assert "access_token=***" in message
