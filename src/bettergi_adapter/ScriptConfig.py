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
import asyncio
from contextlib import suppress

from auto_mas_core import ScriptConfigWorker, TaskMode
from auto_mas_core.host.core import Publisher
from auto_mas_core.host.core_ws import protocol
from auto_mas_core.host.models_schema import WSTaskNoticeData
from auto_mas_core.host.task_proxy_helpers import CONFIG_BASE_NATIVE, read_config_base
from auto_mas_core.host.utils import IS_ELEVATED, ProcessManager, get_logger, process

from .AutoProxy import _BGI_REL_EXE, _BGI_UNKILLABLE_HINT, _wait_bgi_exit
from .tools import one_dragon

logger = get_logger("BetterGI 脚本设置")


class ScriptConfigTask(ScriptConfigWorker):
    """无参数启动 BetterGI 本体，供用户修改程序设置（原生 GUI 原生来源）。"""

    def __init__(self, expander, user, config):
        super().__init__(expander, user, config)
        self.script_config = expander.script_config
        self.cur_user_item = user
        self.use_mas_config = (
            config is None or read_config_base(config) != CONFIG_BASE_NATIVE
        )
        self.process_manager = ProcessManager()
        self.wait_event = asyncio.Event()
        self.crashed = False
        root_path = self.script_config.Info.RootPath
        if root_path is None:
            raise ValueError("RootPath未配置，请检查路径设置")
        self.root_path = root_path
        self.exe_path = self.root_path / _BGI_REL_EXE

    def _cleanup_leftover_slot(self) -> None:
        """清理上一轮残留的 MAS 运行时槽位/物化组（若存在；安全幂等，不误删用户文件）。"""
        if not self.use_mas_config:
            return
        with suppress(Exception):
            # 按账号短 id 前缀扫描删除历史残留物化组（只命中 MAS-{短id}-自定义配置组*，不碰 BGI 本体）
            one_dragon.cleanup_leftover_mas_groups(
                self.root_path, self.script_info.script_id, self.cur_user_item.user_id
            )
        with suppress(Exception):
            # 仅删除确由 MAS 写入的槽位（owner/backup 标记校验在函数内）
            one_dragon.remove_one_dragon_slot(
                self.root_path, self.script_info.script_id
            )

    async def main_logic(self) -> None:
        await self._kill_processes()
        logger.info(f"启动 BetterGI 设置: {self.exe_path}")
        await self.cur_user_item.set_state(status="运行")
        # 任务配置以 MAS 前端为准：GUI 原生来源只打开 BGI 供查看游戏/程序环境，
        # 不再预置一条龙槽位，也不在结束后回读（MAS 前端是唯一编辑入口）。
        self._cleanup_leftover_slot()
        # 仅当 MAS 自身未提权时才走 runas 触发 UAC；已提权时子进程自动继承
        await self.process_manager.open_process(
            self.exe_path,
            elevated=self.script_config.Run.UseAdmin and (not IS_ELEVATED),
        )
        await self.wait_event.wait()

    async def finish(self) -> None:
        self.wait_event.set()
        if not await self._kill_processes():
            # 本任务只负责把 BGI 界面开起来，结束时若关不掉它会一直留着（且 MAS 管不了它），
            # 下次任务带参启动会被这个单实例吞掉 → 任务卡住、游戏不启动。故必须明确告知用户。
            logger.warning(f"BetterGI 设置界面未能自动关闭：{_BGI_UNKILLABLE_HINT}")
            await Publisher.send(
                id=self.task_info.task_id,
                type=protocol.TASK_NOTICE,
                data=WSTaskNoticeData(level="warning", message=_BGI_UNKILLABLE_HINT),
            )
        if not self.crashed:
            logger.success("BetterGI 原生来源配置已打开（任务配置请以 MAS 前端为准）")
            await self.cur_user_item.set_state(status="完成")
        self._cleanup_leftover_slot()

    async def on_crash(self, e: Exception) -> None:
        self.crashed = True
        await self.cur_user_item.set_state(status="异常")
        logger.opt(exception=True).warning(f"BetterGI 设置任务出现异常: {e}")
        with suppress(Exception):
            await self._kill_processes()
        self._cleanup_leftover_slot()
        await Publisher.send(
            id=self.task_info.task_id,
            type=protocol.TASK_NOTICE,
            data=WSTaskNoticeData(
                level="error", message=f"BetterGI 设置任务出现异常: {e}"
            ),
        )

    async def _kill_processes(self) -> bool:
        """中止 BetterGI 进程。

        Returns:
            bool: 已确认无 BetterGI 残留时返回 True；仍有实例存活（MAS 无权终止它，常见于
                BGI 由 MAS 以管理员权限启动而 MAS 未提权）时返回 False。
        """
        try:
            await self.process_manager.kill()
        except Exception as e:
            logger.opt(exception=True).warning(f"通过进程管理器中止 BetterGI 失败: {e}")

        try:
            await process.kill_process(self.exe_path)
        except Exception as e:
            logger.opt(exception=True).warning(f"中止 BetterGI 进程失败: {e}")

        remaining = await _wait_bgi_exit()
        if remaining:
            logger.warning(
                f"BetterGI 进程仍存活（PID: {remaining}）：{_BGI_UNKILLABLE_HINT}"
            )
            return False
        return True


class ScriptViewTask(ScriptConfigTask):
    mode = TaskMode.SCRIPT_VIEW
