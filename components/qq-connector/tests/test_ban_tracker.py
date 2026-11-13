"""全体禁言状态刷新与解除通知的回归测试。"""

from importlib import import_module
from unittest.mock import AsyncMock, Mock

import pytest


services = import_module("plugins.MaiBot-SnowLuma-Adapter-main.services")


@pytest.fixture
def tracker(tmp_path):
    logger = Mock()
    actions = services.QQActionService(logger, Mock(), Mock())
    actions.call_action_data = AsyncMock()
    query_service = services.QQQueryService(actions, logger)
    store = services.QQBanStateStore(logger, tmp_path / "ban_state.json")
    on_lift = AsyncMock()
    tracker = services.QQBanTracker(logger, query_service, on_lift, store)
    return tracker, store, actions, on_lift


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [-1, 1, "-1", "1"])
async def test_active_ban_refreshes_stale_unmuted_cache(tracker, state):
    ban_tracker, store, actions, on_lift = tracker
    record = services.QQBanRecord("123", "0", -1)
    await store.upsert(record)

    # 模拟 SnowLuma：缓存仍未禁言，强制刷新才能得到真实的全体禁言状态。
    async def get_data(action, params):
        assert action == "get_group_info"
        return {"group_all_shut": state if params.get("no_cache") else 0}

    actions.call_action_data.side_effect = get_data
    await ban_tracker._refresh_records_from_remote()

    assert await store.snapshot() == [record]
    on_lift.assert_not_awaited()
    actions.call_action_data.assert_awaited_once_with("get_group_info", {"group_id": "123", "no_cache": True})


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"group_all_shut": None}, {"group_all_shut": "invalid"}, {"group_all_shut": 0.5}])
async def test_unknown_state_keeps_ban_record(tracker, response):
    ban_tracker, store, actions, on_lift = tracker
    record = services.QQBanRecord("123", "0", -1)
    await store.upsert(record)
    actions.call_action_data.return_value = response

    await ban_tracker._refresh_records_from_remote()

    assert await store.snapshot() == [record]
    on_lift.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_query_keeps_ban_record(tracker):
    ban_tracker, store, actions, on_lift = tracker
    record = services.QQBanRecord("123", "0", -1)
    await store.upsert(record)
    actions.call_action_data.side_effect = RuntimeError("remote query failed")

    await ban_tracker._refresh_records_from_remote()

    assert await store.snapshot() == [record]
    on_lift.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [0, "0"])
async def test_confirmed_lift_emits_once(tracker, state):
    ban_tracker, store, actions, on_lift = tracker
    await store.upsert(services.QQBanRecord("123", "0", -1))
    actions.call_action_data.return_value = {"group_all_shut": state}

    await ban_tracker._refresh_records_from_remote()
    await ban_tracker._refresh_records_from_remote()

    assert await store.snapshot() == []
    on_lift.assert_awaited_once()
    assert on_lift.await_args.args[0]["sub_type"] == "whole_lift_ban"


@pytest.mark.asyncio
async def test_explicit_lift_notice_removes_record(tracker):
    ban_tracker, store, actions, on_lift = tracker
    await ban_tracker.record_notice({"notice_type": "group_ban", "sub_type": "ban", "group_id": "123", "user_id": "0"})
    await ban_tracker.record_notice({"notice_type": "group_ban", "sub_type": "lift_ban", "group_id": "123", "user_id": "0"})

    assert await store.snapshot() == []
    on_lift.assert_not_awaited()
    actions.call_action_data.assert_not_awaited()
