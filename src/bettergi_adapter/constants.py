"""BetterGI 的内置组和旧版配置转换。"""

from copy import deepcopy

_BGI_BUILTIN_ONE_DRAGON_GROUPS = [
    "领取邮件",
    "合成树脂",
    "自动幽境危战",
    "自动地脉花",
    "自动首领讨伐",
    "自动秘境",
    "领取尘歌壶奖励",
    "领取每日奖励",
]

_BGI_LEGACY_SERVERS_TO_RESOURCE = {
    "Asia": "亚服",
    "Europe": "欧服",
    "America": "美服",
    "TW,HK,MO": "港澳台服",
}


def _migrate_bgi_account_switch_default(data: dict) -> tuple[dict, bool]:
    """为存量 BetterGI 脚本固化旧默认切号方式 BGI。

    ``Run.AccountSwitchMethod`` 是 v5.6.0 新增字段且类默认值定为 MAS；
    5.5.0 升级上来的存量脚本配置里没有该键，若不补值会随新默认落到 MAS，
    使国际服/第三方登录等不被 MAS 切号支持的用户从「能跑」变「报错」。
    故 load 前缺键注入 ``BGI``（升级前的唯一切号路径）：Run 段缺失（手工
    编辑/截断文件）同样按存量处理；Run 段损坏（非 dict）时跳过注入交给
    load 的纠错路径重建，不在此崩掉启动。显式保存过该键的配置原样保留。

    Returns:
        (迁移后的配置字典, 是否发生了注入)
    """
    normalized_data = deepcopy(data) if isinstance(data, dict) else {}
    if "Run" not in normalized_data:
        normalized_data["Run"] = {}
    run = normalized_data["Run"]
    if isinstance(run, dict) and "AccountSwitchMethod" not in run:
        run["AccountSwitchMethod"] = "BGI"
        return normalized_data, True
    return normalized_data, False
