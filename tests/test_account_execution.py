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


async def test_execution_failure_keeps_completed_daily_count_and_partial_status():
    worker = object.__new__(AutoProxyTask)
    worker.cur_user_config = SimpleNamespace(
        Data=SimpleNamespace(ProxyTimes=0, LastProxyStatus=""),
        Info=SimpleNamespace(RemainedDay=2),
        commit=AsyncMock(),
    )
    worker.cur_user_item = SimpleNamespace(set_state=AsyncMock())
    worker.run_complete = True
    worker.partial_failed_steps = 0
    worker.execution_failure_summary = "执行层未启动"
    await worker._persist_user_run_result()
    worker.cur_user_item.set_state.assert_awaited_once_with(status="部分失败")
    assert worker.cur_user_config.Data.LastProxyStatus == "失败"
    assert worker.cur_user_config.Data.ProxyTimes == 1
    assert worker.cur_user_config.Info.RemainedDay == 1


def test_restore_stygian_copy():
    from bettergi_adapter.tools import backup_archive

    sid, uid = str(uuid4()), str(uuid4())
    old_backup = backup_archive.archive_mas_backup(
        sid, uid, overlay={"Resource": "官服"}
    )
    assert old_backup is not None
    path = backup_archive.mas_user_dir(sid, uid) / "GlobalStygian" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"team":"first"}', encoding="utf-8")
    backup = backup_archive.archive_mas_backup(sid, uid)
    assert backup is not None
    path.write_text('{"team":"second"}', encoding="utf-8")
    backup_archive.restore_mas_backup(sid, uid, backup.name)
    assert json.loads(path.read_text(encoding="utf-8")) == {"team": "first"}

    preview = backup_archive.build_mas_preview(old_backup, None)
    assert any(
        "保留当前设置" in row["value"]
        for section in preview["sections"]
        for row in section["rows"]
    )
    backup_archive.restore_mas_backup(sid, uid, old_backup.name)
    assert json.loads(path.read_text(encoding="utf-8")) == {"team": "first"}


def test_channel_detection_requires_local_client(tmp_path, monkeypatch):
    from pathlib import Path

    from bettergi_adapter.tools import game_info

    def unexpected_access(*args, **kwargs):
        pytest.fail("non-local client reached filesystem")

    monkeypatch.setattr(Path, "read_text", unexpected_access)
    monkeypatch.setattr(Path, "is_file", unexpected_access)
    remote = "//invalid.example/test/YuanShen.exe"
    with pytest.raises(ValueError, match="本机"):
        game_info.detect_channel(Path(remote))
    with pytest.raises(ValueError, match="本机"):
        game_info.resolve_game_exe(tmp_path, remote)


def test_extended_drive_path_is_a_local_game_client():
    from pathlib import PureWindowsPath

    from bettergi_adapter.tools import game_info

    assert (
        game_info.detect_channel(PureWindowsPath("//?/C:/Games/GenshinImpact.exe"))
        == game_info.CHANNEL_GLOBAL
    )


def test_switch_group_is_private_to_account_switching(tmp_path):
    sid, uid = str(uuid4()), str(uuid4())
    reserved = account_switch.GROUP_NAME
    directory = tmp_path / "User" / "ScriptGroup"
    directory.mkdir(parents=True)
    (directory / f"{reserved}.json").write_text('{"name":"reserved"}', encoding="utf-8")
    (directory / "regular.json").write_text('{"name":"regular"}', encoding="utf-8")
    assert one_dragon.list_script_groups(tmp_path) == ["regular"]
    assert (
        one_dragon.read_user_script_group(tmp_path, sid, uid, "regular")["name"]
        == "regular"
    )
    assert one_dragon.read_user_script_group(tmp_path, sid, uid, reserved.lower()) == {}
    with pytest.raises(ValueError, match="临时管理"):
        one_dragon.write_user_script_group(tmp_path, sid, uid, reserved, {})


async def test_whole_phase_failure_reaches_global_report(monkeypatch):
    from contextlib import ExitStack

    from bettergi_adapter import manager

    failed, warning = uuid4(), uuid4()
    expander = object.__new__(manager.BetterGIExpander)
    expander.task_info = SimpleNamespace(mode=manager.TaskMode.AUTO_PROXY)
    expander._ran_account = True
    expander._failed_execution_users = {failed}
    expander._update_root = None
    expander.begin_time = "2026-01-01 12:00:00"
    expander._install_access = ExitStack()
    expander.script_info = SimpleNamespace(
        name="test",
        user_list=[
            SimpleNamespace(uid=uid, status="部分失败") for uid in (failed, warning)
        ],
    )
    expander._render_user_results = lambda **kwargs: ""
    send = AsyncMock()
    monkeypatch.setattr(manager.Notify, "push_proxy_result", send)
    await expander.finish()
    report = send.await_args.kwargs["report"]
    assert (report.completed_count, report.uncompleted_count) == (1, 1)


def test_group_editor_limits_fields_and_keeps_upstream_extensions(
    tmp_path, monkeypatch
):
    from bettergi_adapter import api_service

    sid, uid = str(uuid4()), str(uuid4())
    monkeypatch.setattr(api_service, "_bettergi_script_config", lambda sid: None)
    monkeypatch.setattr(api_service, "_bettergi_user_id", lambda *args: uid)
    monkeypatch.setattr(api_service, "_bettergi_root", lambda config: tmp_path)
    directory = tmp_path / "User" / "ScriptGroup"
    directory.mkdir(parents=True)
    data = {
        "name": "regular",
        "index": 1,
        "config": {},
        "projects": [],
        "upstreamExtension": 42,
    }
    (directory / "regular.json").write_text(json.dumps(data), encoding="utf-8")
    public = api_service.read_script_group(sid, uid, name="regular")
    assert set(public) == {"name", "index", "config", "projects"}
    public["index"] = 2
    target, _ = api_service.save_script_group(sid, uid, name="regular", data=public)
    assert json.loads(target.read_text(encoding="utf-8")) == {**data, "index": 2}
    assert (
        api_service.read_script_group(sid, uid, name=account_switch.GROUP_NAME) is None
    )


def test_queue_assets_stay_within_their_own_directory(tmp_path, monkeypatch):
    sid, uid = str(uuid4()), str(uuid4())
    nested = tmp_path / "User" / "AutoPathing" / "routes" / "daily.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}", encoding="utf-8")
    assert one_dragon._pathing_file_for(tmp_path, "routes/daily") == "routes/daily.json"

    def unexpected(*args, **kwargs):
        pytest.fail("invalid queue reference reached file access")

    monkeypatch.setattr(one_dragon, "_read_per_user_copy", unexpected)
    monkeypatch.setattr(type(tmp_path), "lstat", unexpected)
    for name in ("../outside", "/outside", "Z:/outside", "name:stream"):
        with pytest.raises(ValueError, match="无效"):
            one_dragon.resolve_custom_group(tmp_path, sid, uid, name, name)
        assert one_dragon._keymouse_file_for(tmp_path, name) is None


def test_native_slot_excludes_rejected_references_but_keeps_valid_fallback(tmp_path):
    sid, uid = str(uuid4()), str(uuid4())
    slots = [
        {"kind": "scriptgroup", "name": "regular", "enabled": True},
        {"kind": "pathing", "name": "../outside", "step": "copy-2", "enabled": True},
    ]
    one_dragon.write_user_one_dragon(tmp_path, sid, uid, [], queue=slots)
    saved = one_dragon.load_one_dragon(tmp_path, one_dragon.launch_slot_name())
    definitions = saved["TaskDefinitions"]
    assert "regular" in definitions.values()
    assert not {"../outside", "copy-2"}.intersection(definitions.values())
    assert set(saved["TaskOrder"]) == set(definitions) == set(saved["TaskEnabledList"])


def test_rejected_alias_does_not_remove_a_valid_queue_entry(tmp_path):
    sid, uid = str(uuid4()), str(uuid4())
    rows = [
        {"kind": "scriptgroup", "name": "retired.", "step": "daily-2"},
        {"kind": "scriptgroup", "name": "daily-2", "enabled": True},
    ]
    _, queue = one_dragon.write_user_one_dragon(tmp_path, sid, uid, [], queue=rows)
    native = one_dragon.load_one_dragon(tmp_path, one_dragon.launch_slot_name())
    assert list(native["TaskDefinitions"].values()).count("daily-2") == 1
    assert [row["name"] for row in queue] == ["daily-2"]
