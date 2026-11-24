"""BetterGI专项插件入口。"""

from auto_mas_core import PLUGIN_API_VERSION, Config

_builtin = Config.ScriptConfig.entry_types.get("BetterGIConfig")
if _builtin is not None and _builtin.__module__.startswith("app."):
    raise ImportError(
        "当前 AUTO-MAS 仍内置 BetterGI，请先更新至支持 BetterGI 插件的版本"
    )

from .plugin import Plugin as PLUGIN  # noqa: E402 - 先验证宿主能接手原有托管。

__all__ = ["PLUGIN", "PLUGIN_API_VERSION"]
