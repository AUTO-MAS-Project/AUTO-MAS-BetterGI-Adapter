#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#
#   This file is part of AUTO-MAS.
#
#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of
#   the License, or (at your option) any later version.
#
#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
#   the GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.
from contextlib import ExitStack, suppress
from datetime import datetime

import auto_mas_core.host.core_notify_report as _node_report
from auto_mas_core import TaskMode, UserExpander
from auto_mas_core.host.config import config_manager
from auto_mas_core.host.core import Notify, Publisher
from auto_mas_core.host.core_script_update import ScriptUpdateRequest, run_script_update
from auto_mas_core.host.core_ws import protocol
from auto_mas_core.host.models_notification_report import (
    TaskResultReport,
    UserReportText,
)
from auto_mas_core.host.models_schema import WSTaskNoticeData
from auto_mas_core.host.services import script_install
from auto_mas_core.host.task_run_flow import point
from auto_mas_core.host.utils import LOG_TYPE_ERROR, get_logger, log_box
from auto_mas_core.host.utils_common_fluxdown_cli import FluxdownCancelUnconfirmed

from .AutoProxy import _BGI_REL_EXE, AutoProxyTask
from .ScriptConfig import ScriptConfigTask, ScriptViewTask
from .tools import archive_native_backup, program_update
from .Update import BetterGIUpdateTask

logger = get_logger("BetterGI 调度器")


class BetterGIExpander(UserExpander):
    """在共享的安装目录锁内，逐账号运行 BetterGI。"""

    maintenance = False

    def __init__(self, script, config):
        super().__init__(script, config)
        self._install_access = ExitStack()
        self._program_update_prepared = False
        self._update_root = None
        self._ran_account = False
        self._reports = {}
        self.begin_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def can_run_user(self, entry):
        return super().can_run_user(entry) and (
            self.task_info.mode != TaskMode.AUTO_PROXY or entry.Info.RemainedDay != 0
        )

    async def prepare(self):
        root = self.script_config.Info.RootPath
        if self.task_info.mode != TaskMode.AUTO_PROXY and not self.maintenance:
            if root is None or not (root / _BGI_REL_EXE).is_file():
                raise ValueError("请先设置有效的 BetterGI 脚本路径")
        if root is not None:
            self._install_access.enter_context(script_install.installation_access(root))
            self._update_root = root
            program_update.recover_update_notice(root)
            if self.maintenance:
                await program_update.confirm_safe_game_update(root)
                return
            if self.task_info.mode != TaskMode.AUTO_PROXY:
                await program_update.confirm_current_install(root)
            with suppress(Exception):
                archive_native_backup(root)

    def build_worker(self, user, config):
        if self.maintenance:
            if config is None:
                raise ValueError("更新任务需要指定账号，请刷新后重试")
            return BetterGIUpdateTask(self, user, config)
        worker = {
            TaskMode.AUTO_PROXY: AutoProxyTask,
            TaskMode.SCRIPT_CONFIG: ScriptConfigTask,
            TaskMode.SCRIPT_VIEW: ScriptViewTask,
        }[self.task_info.mode]
        return worker(self, user, config)

    async def spawn(self, child):
        if isinstance(child, AutoProxyTask):
            await self._prepare_script_update()
            reason = await child.check_account()
            if reason != "Pass":
                status = "跳过" if child.user_info.status == "跳过" else "异常"
                await self.record_user_state(
                    child.user_info, status=status, reason=reason
                )
                await Publisher.send(
                    id=self.task_info.task_id,
                    type=protocol.TASK_NOTICE,
                    data=WSTaskNoticeData(level="error", message=reason),
                )
                return
            if self._ran_account:
                await child.wait_game_exit_before_next_user()
            self._ran_account = True
            try:
                await super().spawn(child)
            finally:
                self._reports[child.user_info.uid] = (
                    child.push_log_mode,
                    child.push_log,
                )
        else:
            await super().spawn(child)

    async def _prepare_script_update(self) -> None:
        root = self._update_root
        if root is None:
            return
        if self._program_update_prepared:
            if self.script_config.Update.TakeoverEnabled:
                await program_update.confirm_current_install(root)
            return
        if self.script_config.Update.TakeoverEnabled:
            await self.script_info.set_log("正在检查 BetterGI 本体更新…")

            async def progress(downloaded: int, total: int, speed: float) -> None:
                await self.script_info.set_log(
                    f"BetterGI 更新下载：{downloaded / 1024**2:.1f} / {total / 1024**2:.1f} MB"
                )

            try:
                point(self, "script_update")
                result = await run_script_update(
                    ScriptUpdateRequest(self.script_info.script_id, "BetterGI"),
                    program_update.update_before_run,
                    root,
                    self.script_config,
                    progress=progress,
                )
            except (script_install.InstallUnsafeError, FluxdownCancelUnconfirmed):
                point(self, "script_update", state="failed")
                raise
            except Exception as error:
                point(self, "script_update", state="failed")
                await program_update.confirm_current_install(root)
                result = f"BetterGI 更新准备失败，沿用当前安装继续任务：{error}"
                logger.warning(result)
                with suppress(Exception):
                    await Publisher.send(
                        id=self.task_info.task_id,
                        type=protocol.TASK_NOTICE,
                        data=WSTaskNoticeData(level="warning", message=result),
                    )
            else:
                point(self, "script_update", state="succeeded", key="checked")
            await self.script_info.set_log(result)
            program_update.suppress_update_notice(root)
        else:
            # 关闭接管仍不能启动上轮未确认安装；不发远程请求。
            marker = script_install.workspace(root) / "bgi-install.json"
            if marker.exists():
                raise script_install.InstallUnsafeError(
                    "BetterGI 上次安装未确认，请开启更新托管重试或手动修复"
                )
        self._program_update_prepared = True

    async def finish(self):
        try:
            if self.task_info.mode == TaskMode.AUTO_PROXY and (
                self._ran_account
                or any(user.status == "跳过" for user in self.script_info.user_list)
            ):
                await config_manager.flush()
                users = self.script_info.user_list
                completed = sum(user.status in ("完成", "部分失败") for user in users)
                failed = (
                    len(users)
                    - completed
                    - sum(user.status == "跳过" for user in users)
                )
                result = self._render_user_results(has_uncompleted=bool(failed))
                if result:
                    await self.script_info.set_log(
                        f"{self.script_info.log}\n{result}".strip()
                    )
                title = f"{datetime.now():%m-%d} | {self.script_info.name or '空白'}的自动代理任务报告"
                report = TaskResultReport.from_message(
                    {
                        "title": "自动代理任务报告",
                        "script_name": self.script_info.name or "空白",
                        "start_time": self.begin_time,
                        "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "completed_count": completed,
                        "uncompleted_count": failed,
                        "result": result,
                    }
                )
                try:
                    await Notify.push_proxy_result(
                        title=title, report=report, task_info=self.task_info
                    )
                except Exception as exc:
                    await Publisher.send(
                        id=self.task_info.task_id,
                        type=protocol.TASK_NOTICE,
                        data=WSTaskNoticeData(
                            level="error", message=f"推送代理结果时出现异常: {exc}"
                        ),
                    )
        finally:
            try:
                if self._update_root is not None:
                    program_update.recover_update_notice(self._update_root)
            finally:
                self._install_access.close()

    def _render_user_results(self, *, has_uncompleted: bool) -> str:
        """本专项选择报告条目和展示模式，公共服务只负责排版。"""
        _report_rows = []
        for _report_user in self.script_info.user_list:
            _mode, entries = self._reports.get(_report_user.uid, ("关闭", ()))
            _entries = [
                item
                if isinstance(item, log_box.LogEntry)
                else log_box.LogEntry.from_legacy(item)
                for item in entries
                if (item.log_type if isinstance(item, log_box.LogEntry) else item[0])
                != LOG_TYPE_ERROR
                or has_uncompleted
            ]
            if _mode == "关闭":
                _details = []
            elif _mode == "汇总":
                _details = _node_report.render_aggregate_push_log(_entries)
            else:
                _details = _node_report.render_scatter_push_log(_entries)
            _report_user._completion_details = tuple(_details)
            _report_rows.append(
                UserReportText(
                    name=_report_user.name,
                    result=_report_user.result,
                    detail_lines=tuple(_details),
                )
            )
        return _node_report.render_user_result_text(_report_rows)


class BetterGIUpdateExpander(BetterGIExpander):
    """账号页手动更新，使用同一安装锁和当前目标账号。"""

    maintenance = True
