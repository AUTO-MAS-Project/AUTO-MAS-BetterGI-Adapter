"""账号停止后不再输入；临时凭据及一条龙执行状态与账号配置一致。"""

import asyncio
import importlib
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from bettergi_adapter.AutoProxy import AutoProxyTask
from bettergi_adapter.tools import account_switch, one_dragon
from bettergi_adapter.tools import account_switch_native as native


async def test_cancel_waits_for_switch_before_further_input(monkeypatch):
    started, resume = threading.Event(), threading.Event()
    actions = []

    def find_window(**kwargs):
        started.set()
        resume.wait(3)
        return 1

    monkeypatch.setattr(native, "IS_WINDOWS", True)
    monkeypatch.setattr(
        native, "pyautogui", SimpleNamespace(FAILSAFE=False), raising=False
    )
    monkeypatch.setattr(native, "_dismiss_screensaver", lambda: None)
    monkeypatch.setattr(native, "_find_game_hwnd", find_window)
    monkeypatch.setattr(
        native._game_window,
        "activate_window",
        lambda *a, **kw: actions.append("activate"),
    )
    monkeypatch.setattr(native, "_switch_account_bili", lambda *a: None)
    task = asyncio.create_task(native.async_switch_account("test-user", resource="B服"))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        # 让取消传给后台线程，再次停止也必须等待同一个线程。
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        resume.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not actions
    assert not native._SWITCH_LOCK.locked()


async def test_scrub_credentials_on_process_refusal(tmp_path, monkeypatch):
    mod = importlib.import_module("bettergi_adapter.AutoProxy")
    monkeypatch.setattr(mod, "client_executable_path", lambda user: None)
    monkeypatch.setattr(
        account_switch, "ensure_switch_subscription", lambda *a, **kw: True
    )
    worker = object.__new__(AutoProxyTask)
    worker.script_config = SimpleNamespace(
        Run=SimpleNamespace(AccountSwitchMethod="BGI")
    )
    worker.cur_user_config = SimpleNamespace(
        Info=SimpleNamespace(Id="test@example.org", Password="test-secret"),
        Switch=SimpleNamespace(Resource="官服", Uid=""),
    )
    worker.cur_user_item = SimpleNamespace(name="test")
    worker.script_root_path = tmp_path
    worker.script_exe_path = tmp_path / "BetterGI.exe"
    worker._push_dispatch_log = AsyncMock()
    worker.kill_managed_process = AsyncMock(return_value=False)
    assert not await worker._switch_account()
    path = tmp_path / "User" / "ScriptGroup" / f"{account_switch.GROUP_NAME}.json"
    if path.exists():
        data = path.read_text(encoding="utf-8")
        assert "test-secret" not in data
        assert "test@example.org" not in data


def test_scrub_removes_damaged_temporary_group(tmp_path):
    group = tmp_path / "User" / "ScriptGroup" / f"{account_switch.GROUP_NAME}.json"
    account_switch.scrub_switch_group(tmp_path)
    assert not group.exists()
    group.parent.mkdir(parents=True)
    group.write_text('{"password": "test-secret"', encoding="utf-8")
    account_switch.scrub_switch_group(tmp_path)
    assert not group.exists()


@pytest.mark.parametrize("managed", [False, True])
def test_materialized_queue_preserves_switches_and_instance_copies(tmp_path, managed):
    sid, uid = str(uuid4()), str(uuid4())
    worker = object.__new__(AutoProxyTask)
    worker.script_root_path = tmp_path
    worker.cur_user_item = SimpleNamespace(user_id=uid, name="test")
    worker.script_info = SimpleNamespace(script_id=sid)
    worker.cur_user_config = SimpleNamespace(
        OneDragon=SimpleNamespace(
            PartyName="", DailyRewardPartyName="", AutoBossStrategyName=""
        )
    )
    worker.use_mas_config = worker.use_execution_layer = worker.custom_exec_enabled = (
        True
    )
    worker.use_custom_groups = managed
    worker.one_dragon_groups = []
    worker.plan_combat_bases = set()
    worker.plan_mode = worker.drop_statistics_enabled = False
    worker.exec_plan_steps = []
    worker.default_strategy_path = ""
    name = "Example"
    worker.one_dragon_custom_groups = [{"name": "Disabled", "enabled": False}]
    worker.one_dragon_queue = [
        {"kind": "scriptgroup", "name": "Disabled"},
        {"kind": "scriptgroup", "name": name, "enabled": True},
        {"kind": "scriptgroup", "name": name, "step": "Example-2", "enabled": True},
    ]
    seed = one_dragon.per_user_one_dragon_path(sid, uid, one_dragon.launch_slot_name())
    one_dragon.write_file(
        seed,
        {
            "TaskDefinitions": {"old": "Disabled"},
            "TaskOrder": ["old"],
            "TaskEnabledList": {"old": managed},
        },
    )
    for n in ("Disabled", name, "Example-2"):
        one_dragon.write_file(
            one_dragon.per_user_script_group_path(sid, uid, n),
            {"config": {"name": n}, "projects": [{"name": n}]},
        )
    for _ in range(2):
        worker._write_one_dragon_config()
        projects = [
            json.loads(path.read_text(encoding="utf-8"))["projects"][0]["name"]
            for path in worker._materialized_exec_groups
        ]
        assert projects == [name, "Example-2"]

    worker.one_dragon_queue = [worker.one_dragon_queue[1]]
    worker._write_one_dragon_config()
    config = one_dragon.load_one_dragon(tmp_path, one_dragon.launch_slot_name())
    assert "Example-2" not in config["TaskDefinitions"].values()
    assert "MasDisabledExecutionGroups" not in config


@pytest.mark.parametrize("value", [None, {}, {"TaskEnabledList": []}])
def test_unreadable_native_plan_cannot_report_an_empty_run(tmp_path, value):
    worker = object.__new__(AutoProxyTask)
    worker.script_root_path = tmp_path
    worker.launch_config_name = "daily"
    worker.cur_user_item = SimpleNamespace(name="test")
    path = one_dragon.one_dragon_path(tmp_path, "daily")
    if value is not None:
        one_dragon.write_file(path, value)
    with pytest.raises(ValueError, match="daily"):
        worker._native_one_dragon_has_tasks()
    one_dragon.write_file(path, {"TaskEnabledList": {}})
    assert worker._native_one_dragon_has_tasks() is False


@pytest.mark.parametrize("method", ["MAS", "BGI"])
async def test_bound_client_starts_without_login(method, monkeypatch):
    mod = importlib.import_module("bettergi_adapter.AutoProxy")
    monkeypatch.setattr(mod, "client_executable_path", lambda user: "bound-game.exe")
    worker = object.__new__(AutoProxyTask)
    worker.script_config = SimpleNamespace(
        Run=SimpleNamespace(AccountSwitchMethod=method)
    )
    worker.cur_user_config = SimpleNamespace(Info=SimpleNamespace(Id=""))
    worker._ensure_user_game_running = AsyncMock()
    assert await worker._switch_account()
    worker._ensure_user_game_running.assert_awaited_once_with("bound-game.exe")


async def test_fatal_log_wins_over_group_end(monkeypatch):
    mod = importlib.import_module("bettergi_adapter.AutoProxy")

    class Monitor:
        def __init__(self, time_range, time_format, callback):
            self.callback = callback

        async def start_monitor_file(self, path, start):
            await self.callback(
                ["MAS_PLAN_FAIL: test", '配置组 "group" 执行结束'], start
            )

        async def stop(self):
            pass

    monkeypatch.setattr(mod, "LogMonitor", Monitor)
    monkeypatch.setattr(mod, "point", lambda *args: None)
    log = SimpleNamespace(set_state=AsyncMock(), content=[])
    worker = object.__new__(AutoProxyTask)
    worker.exec_group_names = ["group"]
    worker.cur_user_item = SimpleNamespace(
        name="test", add_log_record=AsyncMock(return_value=log)
    )
    worker.script_exe_path = "BetterGI.exe"
    worker.script_target_process_info = None
    worker.script_config = SimpleNamespace(Run=SimpleNamespace(UseAdmin=False))
    worker.log_time_range = worker.log_time_format = None
    worker.kill_managed_process = AsyncMock(return_value=True)
    worker.bettergi_process_manager = SimpleNamespace(open_process=AsyncMock())
    worker._push_dispatch_log = AsyncMock()
    assert not await worker._run_execution_layer()
    assert "致命" in log.set_state.await_args.kwargs["status"]


@pytest.mark.parametrize("submit_plan", [False, True])
def test_queue_update_keeps_submitted_plan_edits(tmp_path, submit_plan):
    from bettergi_adapter.api_service import prepare_user_update

    script = SimpleNamespace(uid=uuid4(), Info=SimpleNamespace(RootPath=str(tmp_path)))
    old = [
        {"uid": "domain", "name": "自动秘境", "settings": {"domainName": "old"}},
        {"uid": "boss", "name": "自动首领讨伐", "settings": {}},
    ]

    def plan(steps):
        return json.dumps({"version": 1, "steps": steps}, ensure_ascii=False)

    user = SimpleNamespace(
        uid=uuid4(), OneDragon=SimpleNamespace(Plan=plan(old), Groups=[])
    )
    od = {
        "Queue": json.dumps(
            [{"name": "自动秘境", "planUid": "domain"}], ensure_ascii=False
        ),
    }
    if submit_plan:
        od["Plan"] = plan([{**old[0], "settings": {"domainName": "new"}}, old[1]])
    prepare_user_update(script, user, data={"OneDragon": od})
    steps = json.loads(od["Plan"])["steps"]
    assert [(step["uid"], step["settings"]["domainName"]) for step in steps] == [
        ("domain", "new" if submit_plan else "old")
    ]


@pytest.mark.parametrize("flag", [False, "false"])
def test_daily_team_lookup_uses_daily_domain(flag):
    from bettergi_adapter.tools.team_resolver import _resolve_domain_name

    assert (
        _resolve_domain_name(
            {
                "domainName": "daily",
                "weeklyDomainEnabled": flag,
                "weeklyDomain": {"default": {"domainName": "weekly"}},
            },
            "Monday",
        )
        == "daily"
    )
