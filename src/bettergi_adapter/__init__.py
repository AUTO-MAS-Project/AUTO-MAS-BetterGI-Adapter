"""BetterGI专项插件入口。"""

from dataclasses import fields

from auto_mas_core import (
    PLUGIN_API_VERSION,
    Config,
    ScriptAdapterPlugin,
    ScriptTypeDecl,
)

_builtin = Config.ScriptConfig.entry_types.get("BetterGIConfig")
if _builtin is not None and _builtin.__module__.startswith("app."):
    raise ImportError(
        "当前 AUTO-MAS 仍内置 BetterGI，请先更新至支持 BetterGI 插件的版本"
    )

# 同一开发版本可能包含不同阶段的 SDK；加载业务模块前先确认它能完整接管。
if not {"maintenance_expander", "desktop_session", "restore_pools"} <= {
    field.name for field in fields(ScriptTypeDecl)
} or not hasattr(ScriptAdapterPlugin, "prepare_user_update"):
    raise ImportError("请更新 AUTO-MAS 至支持 BetterGI 插件的版本，再安装或启用插件")

from .plugin import Plugin as PLUGIN  # noqa: E402 - 先验证宿主能接手原有托管。

__all__ = ["PLUGIN", "PLUGIN_API_VERSION"]
