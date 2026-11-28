#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team

#   This file is part of AUTO-MAS.

#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of
#   the License, or (at your option) any later version.

#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
#   the GNU Affero General Public License for more details.

#   You should have received a copy of the GNU Affero General Public License
#   along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.

#   Contact: DLmaster_361@163.com


from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Literal, cast

from auto_mas_core import (
    DeclarativeBlock,
    HostBlock,
    PluginBlock,
    ScriptEntry,
    UserEntry,
)
from auto_mas_core.host.config import (
    ConfigCollection,
    ConfigGroup,
    FieldChangeEvent,
    UiVisibility,
    Virtual,
    collection,
    encrypted,
    legacy,
    ui,
    virtual_field,
)
from auto_mas_core.host.config_hints import migrate_legacy_fields
from auto_mas_core.host.config_types import (
    FilePath,
    FolderPath,
    JsonListString,
)
from auto_mas_core.host.models_config_queue import Webhook
from auto_mas_core.host.models_config_shared import (
    AccountCredentialFields,
    AccountNameFields,
    AccountRunFields,
    AccountRunStatusFields,
    AccountScriptHookFields,
    _tag_last_status,
    _tag_notes,
    _tag_remained_days,
    none_as,
)
from auto_mas_core.host.utils import constants as _utils_constants
from pydantic import Field

from .constants import (
    _BGI_LEGACY_SERVERS_TO_RESOURCE,
    _migrate_bgi_account_switch_default,
)


class DesktopSessionRunFields(ConfigGroup):
    """支持桌面分身的托管运行设置。"""

    ExecutionSession: Literal["main", "desktop"] = Field(
        default="main", description="单独启动托管时使用的 Windows 会话"
    )


class BetterGIUserConfig(UserEntry):
    "BetterGI 账号配置（更好的原神）"

    ui_native_session = "config"
    ui_blocks = (
        HostBlock("config_restore"),
        HostBlock("native_session"),
        DeclarativeBlock(("Info",)),
        PluginBlock(page_id="user", fallback_groups=("Switch", "Task", "OneDragon")),
        DeclarativeBlock(("Notify",)),
        HostBlock("webhooks"),
    )

    class DataFields(AccountRunFields, AccountRunStatusFields): ...

    Data: DataFields = Field(default_factory=DataFields)

    class InfoFields(
        AccountNameFields, AccountCredentialFields, AccountScriptHookFields
    ):
        Base: Annotated[
            Literal["shared", "independent", "native"],
            legacy(
                group="Info",
                name="Mode",
                convert=_utils_constants.normalize_base_source,
            ),
            ui(options=["independent", "native"]),
        ] = Field(
            default_factory=lambda: "independent",
            description="base 来源（shared=共享/independent=独立/native=原生）",
        )

        Id: Annotated[str, encrypted()] = Field(
            description="账号", default_factory=lambda: ""
        )

        IfQuickConfig: Annotated[bool, ui(visibility=UiVisibility.HIDE)] = Field(
            default_factory=lambda: True,
            description="是否启用覆写常规配置（与配置来源独立，按账号保存）",
        )

        Password: Annotated[str, encrypted()] = Field(
            description="密码", default_factory=lambda: ""
        )

    Info: InfoFields = Field(default_factory=InfoFields)

    class NotifyFields(ConfigGroup):
        Enabled: bool = Field(
            default_factory=lambda: False, description="是否启用账号通知"
        )

        IfSendDropStatistics: bool = Field(
            default_factory=lambda: True,
            description="是否统计掉落（BGI「奖励识别」）：默认开启；开启后运行前强制打开奖励识别， 并把日志里的逐轮识别结果汇总进统计通知",
        )

        IfSendMail: bool = Field(
            default_factory=lambda: False, description="是否发送邮件"
        )

        IfSendStatistic: bool = Field(
            default_factory=lambda: False, description="是否发送账号统计信息"
        )

        IfServerChan: bool = Field(
            default_factory=lambda: False, description="是否启用 Server 酱"
        )

        PushLogMode: Literal["关闭", "逐条", "汇总"] = Field(
            default_factory=lambda: "汇总",
            description="任务报告节点详情的推送模式（一条龙/执行层分步表）： 关闭 = 不注入；逐条 = 逐条带回时间戳；汇总 = 按状态聚合",
        )

        ServerChanKey: str = Field(
            default_factory=lambda: "", description="Server 酱密钥"
        )

        ToAddress: str = Field(
            default_factory=lambda: "", description="账号通知收件地址"
        )

    Notify: NotifyFields = Field(default_factory=NotifyFields)

    class OneDragonFields(ConfigGroup):
        AutoBossStrategyName: str = Field(
            default_factory=lambda: "",
            description="战斗策略（对应 BetterGI 一条龙的 AutoBossStrategyName，留空不覆盖） 默认「根据队伍自动选择」为 BetterGI 内置策略名",
        )

        CustomGroups: JsonListString = Field(
            default_factory=lambda: "[]",
            description='自定义配置组列表：JSON 数组字符串，元素为 {"name": str, "enabled": bool}',
        )

        DailyRewardPartyName: str = Field(
            default_factory=lambda: "",
            description="领取奖励队伍（对应 BetterGI 一条龙的 DailyRewardPartyName，留空不覆盖）",
        )

        Groups: list[str] = Field(
            default_factory=lambda: [
                "领取邮件",
                "合成树脂",
                "自动幽境危战",
                "自动地脉花",
                "自动首领讨伐",
                "自动秘境",
                "领取尘歌壶奖励",
                "领取每日奖励",
            ],
            description="一条龙要执行的内置配置组（按组名，默认全部 8 组开启）",
        )

        IfUseCustomGroups: bool = Field(
            default_factory=lambda: False,
            description="是否管理自定义配置组（总开关；OFF 时沿 BetterGI 原生设置，自定义组原样保留）",
        )

        IfUseTeams: bool = Field(
            default_factory=lambda: False,
            description="「队伍配置」总开关（胶囊开关）：ON 时表格内队伍参与运行时「战斗场景」选队； OFF 时数据保留但不参与匹配（通用队伍 PartyName/AutoBossStrategyName 照旧生效）。",
        )

        PartyName: str = Field(
            default_factory=lambda: "",
            description="战斗队伍（对应 BetterGI 一条龙的通用 PartyName，留空不覆盖）",
        )

        Plan: str = Field(
            default_factory=lambda: "",
            description="一条龙执行计划（Plan）JSON 字符串：{version, steps:[{uid,kind,name,enabled,settings}]}。 战斗 4 项（自动秘境/自动地脉花/自动幽境危战/自动首领讨伐）直连执行层时由本字段 承载其 per-任务参数；右栏对应设置仅写入本字段（不落原生一条龙配置）。",
        )

        Queue: JsonListString = Field(
            default_factory=lambda: "[]",
            description='一条龙队列（可视化编排）：JSON 数组字符串，按执行顺序存储，元素为 {"kind": str, "name": str}（kind ∈ builtin/js/pathing/scriptgroup/custom， 内置组名命中时后端强制 builtin）。仅表达顺序与成员（含同名重复实例）， 行启停仍由 Groups / CustomGroups 承载；为空或非法时回退旧行为 （按副本 TaskOrder 相对顺序，不重排）。',
        )

        Teams: JsonListString = Field(
            default_factory=lambda: "[]",
            description='队伍配置表：JSON 数组字符串，数组顺序即界面展示顺序（可拖拽重排），元素为 {"name": str,            # 队伍名称（游戏内队伍名） "strategy": str,        # 战斗策略名（留空 = 跟随通用策略 AutoBossStrategyName） "scenes": {             # 战斗场景（可跨标签页任意叠加，空则本行不参与匹配） "domain": [{"region": str, "domain": str, "reward": str}],   # 秘境：地区/秘境名/奖励档 "leyline": [{"country": str, "type": str}],                  # 地脉花：地区/地脉类型 "boss": [{"region": str, "boss": str}]},                     # 首领讨伐：地区/首领名 "note": str,            # 备注 "enabled": bool}        # 启用状态 序号 0 的「通用队伍」不落本字段（直绑 PartyName / AutoBossStrategyName）。 运行期由 team_resolver 按 L1 精确匹配 + 随机选取，写入 Plan 步骤的 masTeamOverride / masStrategyOverride（最高优先级，压过每周行与步骤级字段）。',
        )

        UseExecutionLayer: bool = Field(
            default_factory=lambda: True,
            description="是否启用「直连执行层」：战斗 4 项由 MAS 自编排 Plan 驱动（按需求恒开，预留开关）。",
        )

    OneDragon: OneDragonFields = Field(default_factory=OneDragonFields)

    class SwitchFields(ConfigGroup):
        GamePath: FilePath = Field(
            default_factory=lambda: None,
            description="游戏客户端路径（账号级覆盖，可空）：官服/B服/国际服是三个互相隔离的客户端， B站账号只能登录B服客户端。留空 = 跟随 BetterGI 全局配置的游戏路径；填写后该账号运行时由 MAS 按此路径临时拉起游戏（不修改 BetterGI 配置），实现同托管 混服账号各用各的客户端",
        )

        Resource: Literal["官服", "B服", "亚服", "欧服", "美服", "港澳台服"] = Field(
            default_factory=lambda: "官服",
            description="切换账号配置（BetterGI「切换账号多模式」脚本专项适配） 账号/密码复用 Info.Id / Info.Password（密码经 EncryptValidator 加密） 切换模式不再由账号配置，运行时按密码是否填写推断： 填密码 → 「账号+密码+OCR」，未填 → 「下拉列表」；B服 强制「B服切换另一个账号匹配+键鼠」。 游戏服务器（账号所在服务器：官服/B服/国际服各服务器）",
        )

        Uid: str = Field(
            default_factory=lambda: "",
            description="账号 UID（可不填，切换前识别一致将不执行切换动作；仅 BetterGI 脚本方式生效）",
        )

    Switch: SwitchFields = Field(default_factory=SwitchFields)

    class TaskFields(ConfigGroup):
        OneDragonConfigName: str = Field(
            default_factory=lambda: "",
            description="BetterGI「一条龙」配置名，对应脚本一条龙页面中已保存的配置名称",
        )

    Task: TaskFields = Field(default_factory=TaskFields)
    Notify_CustomWebhooks: ConfigCollection[Webhook] = collection(Webhook)

    def getTags(self) -> str:
        tags = []
        last_status = self.Data.LastProxyStatus
        tags.append(
            {
                "text": f"上次：{_tag_last_status(last_status)}",
                "color": "red" if last_status == "失败" else "green",
            }
        )
        if self.Info.IfQuickConfig:
            config_name = "MAS独立配置"
        else:
            config_name = self.Task.OneDragonConfigName or "未设置"
        tags.append({"text": f"一条龙：{config_name}", "color": "orange"})
        tags.append(_tag_remained_days(self))
        tags.append(_tag_notes(self))
        return json.dumps(tags, ensure_ascii=False)

    @classmethod
    def normalize_payload(cls, data):
        data = deepcopy(data)
        normalized_data = deepcopy(data) if isinstance(data, dict) else {}
        switch = normalized_data.get("Switch")
        if isinstance(switch, dict) and "Resource" not in switch:
            if switch.get("Modes") == "B服切换另一个账号匹配+键鼠":
                switch["Resource"] = "B服"
            elif switch.get("GlobalAccount"):
                server = switch.get("Servers")
                switch["Resource"] = (
                    _BGI_LEGACY_SERVERS_TO_RESOURCE.get(server, "亚服")
                    if isinstance(server, str)
                    else "亚服"
                )
            else:
                switch["Resource"] = "官服"
        normalized_data = migrate_legacy_fields(cls, normalized_data)
        info = normalized_data.get("Info")
        if isinstance(info, dict):
            base = info.get("Base")
            if base in ("shared", "independent", "native"):
                info["IfQuickConfig"] = base != "native"
        return normalized_data

    @virtual_field("Info.Tag")
    def compute_Info_Tag(self):
        try:
            return self.getTags()
        except Exception as exc:
            return str(exc)

    class Metadata(UserEntry.Info):
        config_path: Virtual[str] = None
        name: Virtual[str] = None
        enabled: Virtual[bool] = None

    info: Metadata = Field(default_factory=Metadata)

    @virtual_field("info.name")
    def plugin_name(self):
        return self.Info.Name

    @virtual_field("info.config_path")
    def plugin_config_path(self):
        """账号编辑目录恒按托管和账号分桶。"""
        from auto_mas_core import Config

        users = self.parent
        script = users.parent if users is not None else None
        if not isinstance(script, BetterGIConfig):
            return ""
        return str(Config.data_path / str(script.uid) / str(self.uid))

    @virtual_field("info.enabled")
    def plugin_enabled(self):
        return self.Info.Status

    async def _activate_from_payload(self, payload, *, regenerate_uuids=False):
        await super()._activate_from_payload(
            type(self).normalize_payload(payload), regenerate_uuids=regenerate_uuids
        )

    @staticmethod
    async def apply_config_source(
        user: BetterGIUserConfig, event: FieldChangeEvent
    ) -> None:
        """来源切换时同步运行路径使用的旧开关。"""
        user.Info.IfQuickConfig = event.value != "native"
        await user.commit()


BetterGIUserConfig.connect(
    BetterGIUserConfig.apply_config_source, phase="runtime", group="Info", field="Base"
)


class BetterGIConfig(ScriptEntry):
    "BetterGI 配置（更好的原神，原生 GUI 原生来源 + 仅一条龙任务）"

    ui_blocks = (
        DeclarativeBlock(("Info",)),
        HostBlock("game_binding"),
        DeclarativeBlock(("Run", "Game", "Update")),
    )

    class UpdateFields(ConfigGroup):
        TakeoverEnabled: bool = Field(
            default=False,
            description="运行前由 MAS 下载校验 BetterGI 官方安装包并静默更新，普通检查下载失败后沿用当前安装；运行期暂时屏蔽本体更新提示，结束恢复",
        )
        Channel: Literal["stable", "beta"] = Field(
            default="stable", description="BetterGI 正式版或公测版（上游 alpha）"
        )
        MirrorChyanCDK: Annotated[str, encrypted()] = Field(
            default="",
            description="BetterGI Mirror 酱 CDK，留空使用全局 CDK，无 CDK 使用 GitHub",
        )

    Update: UpdateFields = Field(default_factory=UpdateFields)

    class GameFields(ConfigGroup):
        CloseOnFinish: bool = Field(
            default_factory=lambda: True, description="任务结束后关闭游戏"
        )

        Controller: Annotated[
            Literal["电脑端-前台", "电脑端-云原神", "电脑端-桌面分身"],
            ui(visibility=UiVisibility.DISABLE),
        ] = Field(
            default_factory=lambda: "电脑端-前台",
            description="控制器（游戏控制方式：电脑端-前台 / 电脑端-云原神 / 电脑端-桌面分身） ⚠️ 预留字段：当前运行时不读取（BetterGI 自行管理游戏控制），云原神 / 桌面分身 尚未开发。为将来支持而保留占位并持久化，恒为默认「电脑端-前台」，勿被判定死代码误删。",
        )

        IfAutoUpdate: bool = Field(
            default_factory=lambda: False,
            description="是否在启动 BetterGI 前由 MAS 检查并接管原神客户端更新",
        )

    Game: GameFields = Field(default_factory=GameFields)

    class InfoFields(ConfigGroup):
        Name: str = Field(
            description="托管名称", default_factory=lambda: "新 BetterGI 托管"
        )

        RootPath: FolderPath = Field(
            description="脚本根目录", default_factory=lambda: None
        )

    Info: InfoFields = Field(default_factory=InfoFields)

    class RunFields(DesktopSessionRunFields):
        AccountSwitchMethod: Literal["BGI", "MAS"] = Field(
            default_factory=lambda: "MAS",
            description="账号切换方式（托管级，参考 MaaEnd Run.AccountSwitchMethod）： BGI = BetterGI「切换账号多模式」脚本执行（国际服请改用此方式）；MAS = MAS 侧 前台 OCR 直接操控游戏切号（官服/B服，游戏由 MAS 托管启动），官服/B服推荐。 默认值双轨：新建托管取类默认 MAS；既有托管（配置无该键）由 load 迁移固化 旧默认 BGI（见 _migrate_bgi_account_switch_default），保持升级前行为。",
        )

        HardTimeLimit: Annotated[int, Field(ge=1, le=9999), none_as(1)] = Field(
            default_factory=lambda: 120,
            description="单账号运行总时限（分钟），包含等待和全部重试",
        )

        ProxyTimesLimit: Annotated[int, Field(ge=0, le=9999), none_as(0)] = Field(
            description="每日代理次数限制", default_factory=lambda: 0
        )

        RunTimeLimit: Annotated[int, Field(ge=1, le=9999), none_as(1)] = Field(
            description="日志超时限制", default_factory=lambda: 10
        )

        RunTimesLimit: Annotated[int, Field(ge=1, le=9999), none_as(1)] = Field(
            description="重试次数限制", default_factory=lambda: 3
        )

        UseAdmin: bool = Field(
            default_factory=lambda: True,
            description="是否以管理员权限启动 BetterGI。默认提权（贴近旧行为）；若 MAS 平时以非管理员 运行、又不希望每次启动 BGI 都弹 UAC（无人值守任务尤其容易挂在授权上），可关闭。 MAS 自身已提权时，即使此处开启，也不会重复触发 UAC（子进程自动继承管理员令牌）。",
        )

    Run: RunFields = Field(default_factory=RunFields)
    users: ConfigCollection[BetterGIUserConfig] = collection(BetterGIUserConfig)

    class Metadata(ScriptEntry.Info):
        name: Virtual[str] = None  # pyright: ignore[reportIncompatibleVariableOverride]

    info: Metadata = Field(default_factory=Metadata)  # pyright: ignore[reportIncompatibleVariableOverride]

    @virtual_field("info.name")
    def plugin_name(self):
        """向宿主提供已有托管名称。"""
        return self.Info.Name

    @classmethod
    def normalize_payload(cls, data):
        """迁移原账号集合名称，保留 UID、顺序及字段。"""
        data, _ = _migrate_bgi_account_switch_default(data)
        if "UserData" in data:
            data["users"] = data.pop("UserData")
        if "UserData" in data.get("SubConfigsInfo", {}):
            data["SubConfigsInfo"]["users"] = data["SubConfigsInfo"].pop("UserData")
        return data

    async def _activate_from_payload(self, payload, *, regenerate_uuids=False):
        """在集合激活边界转换旧配置文档。"""
        await super()._activate_from_payload(
            type(self).normalize_payload(payload), regenerate_uuids=regenerate_uuids
        )

    @staticmethod
    def validate_root_path(_script: BetterGIConfig, event: FieldChangeEvent) -> None:
        """保留原编辑页对 BetterGI 安装目录的检查。"""
        path = cast(Path | None, event.value)
        if path is not None and not (path / "BetterGI.exe").is_file():
            raise ValueError("所选目录中没有 BetterGI.exe")


BetterGIConfig.connect(
    BetterGIConfig.validate_root_path, phase="runtime", group="Info", field="RootPath"
)
