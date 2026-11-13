from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace

import sys

import pytest


PACKAGE = "qq_file_chain_test"
package = ModuleType(PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[PACKAGE] = package


@pytest.mark.asyncio
async def test_receive_file_remains_structured_without_download():
    codec_type = import_module(f"{PACKAGE}.codecs.inbound.message_codec").QQInboundCodec
    codec = codec_type(None, None, SimpleNamespace(), lambda: SimpleNamespace())
    segments, _ = await codec.convert_segments({"message": [{"type": "file", "data": {
        "file_id": "qq-file", "name": "report.csv", "size": 42, "busid": 102,
    }}]}, "123")
    assert segments == [{"type": "file", "data": {"file_id": "qq-file", "name": "report.csv", "size": 42, "busid": 102}}]


@pytest.mark.parametrize("profile_name,action", [("NAPCAT_PROFILE", "send_group_msg"), ("SNOWLUMA_PROFILE", "upload_group_file")])
def test_file_send_uses_host_http_url_for_both_profiles(profile_name, action):
    profiles = import_module(f"{PACKAGE}.profile")
    profile = profiles.NAPCAT_PROFILE if profile_name == "NAPCAT_PROFILE" else profiles.SNOWLUMA_PROFILE
    codec = import_module(f"{PACKAGE}.codecs.outbound.message_codec").QQOutboundCodec(SimpleNamespace(profile=profile))
    url = "https://host.example/api/files/transfers/test-ticket"
    actions = codec.build_outbound_actions({"message_info": {"group_info": {"group_id": "456"}},
                                          "raw_message": [{"type": "file", "data": {"file_ref": "host-ref", "name": "a.txt", "url": url}}]}, {})
    assert len(actions) == 1 and actions[0][0] == action
    params = actions[0][1]
    encoded = params if profile.split_file_upload else params["message"][0]["data"]
    assert encoded["file"] == url and encoded["name"] == "a.txt"


@pytest.mark.asyncio
async def test_resolve_group_and_private_file_locations():
    mixin = import_module(f"{PACKAGE}.apis.file").QQFileApiMixin
    calls = []
    class Adapter(mixin):
        async def _call_napcat_action_data(self, action, params):
            calls.append((action, params))
            return {"url": "https://download.example/a"}
    adapter = Adapter()
    await adapter.api_resolve_file({"platform": "qq", "group_id": "456", "file_id": "id", "busid": 102})
    await adapter.api_resolve_file({"platform": "qq", "user_id": "789", "file_id": "private"})
    assert calls == [("get_group_file_url", {"file_id": "id", "group_id": 456, "busid": 102}),
                     ("get_private_file_url", {"file_id": "private", "user_id": 789})]


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{}, {"busid": 0}, {"busid": "0"}])
async def test_resolve_group_file_omits_unknown_busid(metadata):
    mixin = import_module(f"{PACKAGE}.apis.file").QQFileApiMixin
    calls = []

    class Adapter(mixin):
        async def _call_napcat_action_data(self, action, params):
            calls.append((action, params))
            # SnowLuma 接收显式 0 时会覆盖默认业务类型，导致 QQ 返回参数错误。
            if params.get("busid") == 0:
                raise RuntimeError("group file url failed: code=4294966993 msg=参数错误")
            return {"url": "https://download.example/a"}

    result = await Adapter().api_resolve_file({
        "platform": "qq", "group_id": "456", "file_id": "/group-file", **metadata,
    })

    assert result == {"url": "https://download.example/a"}
    assert calls == [("get_group_file_url", {"file_id": "/group-file", "group_id": 456})]
