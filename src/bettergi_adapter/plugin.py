"""注册 BetterGI 的托管、账号、维护操作和原有编辑接口。"""

from auto_mas_core import Config, ScriptAdapterPlugin, ScriptTypeDecl, TaskMode
from auto_mas_core.host.utils import IS_ELEVATED
from fastapi import APIRouter

from .api import panel_router
from .api import router as editor_router
from .api_service import prepare_user_update
from .config import BetterGIConfig, BetterGIUserConfig
from .manager import BetterGIExpander, BetterGIUpdateExpander
from .tools.restore_service import RESTORE_POOLS

router = APIRouter()
router.include_router(editor_router, prefix="/api/scripts", tags=["脚本管理"])
router.include_router(
    editor_router, prefix="/api/plugin/bettergi_adapter", include_in_schema=False
)
router.include_router(panel_router, prefix="/api/plugin/bettergi_adapter")


def supports_desktop_session(config):
    return (
        not config.Run.UseAdmin or IS_ELEVATED
    ) and not config.Update.TakeoverEnabled


class Plugin(ScriptAdapterPlugin):
    script_type_key = "BetterGI"
    api_router = router
    decl = ScriptTypeDecl(
        script_type=BetterGIConfig,
        user_type=BetterGIUserConfig,
        expander_class=BetterGIExpander,
        maintenance_expander=BetterGIUpdateExpander,
        supported_modes=(
            TaskMode.AUTO_PROXY,
            TaskMode.SCRIPT_CONFIG,
            TaskMode.SCRIPT_VIEW,
        ),
        game_kinds=("client",),
        activity_game="genshin",
        desktop_session=supports_desktop_session,
        restore_pools=tuple(RESTORE_POOLS),
    )

    async def prepare_user_update(self, script, user, data):
        prepare_user_update(script, user, data=data)

    async def pre_enable(self):
        refs = {"PlanConfig": Config.PlanConfig, "games": Config.GameConfig}
        BetterGIConfig.related_config = refs
        BetterGIUserConfig.related_config = refs
