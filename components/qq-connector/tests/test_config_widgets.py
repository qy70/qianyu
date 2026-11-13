from importlib import import_module
from unittest.mock import AsyncMock

import asyncio
import pytest

from maibot_sdk.config_widgets import ConfigWidgetSnapshot

Plugin = import_module("plugins.MaiBot-SnowLuma-Adapter-main.plugin").SnowLumaAdapterPlugin


def test_connection_snapshot_has_no_fake_qrcode():
    async def run():
        plugin = Plugin()
        plugin.set_plugin_config(plugin.get_default_config())
        states = await plugin.get_config_widget_state()
        ConfigWidgetSnapshot(widgets=plugin.config_widgets, states=states)
        assert {widget.kind for widget in plugin.config_widgets} == {"status", "action"}
        assert states["connection"].text
        with pytest.raises(ValueError):
            await plugin.on_config_widget_action("invalid")

    asyncio.run(run())


def test_reconnect_calls_transport_restart(monkeypatch):
    async def run():
        plugin = Plugin()
        restart = AsyncMock()
        monkeypatch.setattr(plugin, "_restart_connection_if_needed", restart)
        await plugin.on_config_widget_action("reconnect")
        restart.assert_awaited_once()

    asyncio.run(run())
