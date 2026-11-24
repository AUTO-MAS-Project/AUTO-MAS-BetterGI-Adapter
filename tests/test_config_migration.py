"""旧版集合经宿主转换后，仍以同一托管和账号身份读写。"""

from uuid import uuid4

import pytest
from app.config import ConfigCollection, config_manager
from app.core.config.upgrade import convert_legacy
from app.utils import io

from bettergi_adapter.config import BetterGIConfig


@pytest.mark.parametrize("legacy_children", [False, True])
async def test_legacy_accounts_survive_save_and_reload(tmp_path, legacy_children):
    sid, first, second = [str(uuid4()) for _ in range(3)]
    payload = {
        "order": [{"uid": sid, "type": "BetterGIConfig"}],
        "data": {
            sid: {
                "Info": {"Name": "原托管"},
                "UserData": {
                    "order": [
                        {"uid": uid, "type": "BetterGIUserConfig"}
                        for uid in (first, second)
                    ],
                    "data": {
                        uid: {
                            "Info": {
                                "Name": uid,
                                "Status": True,
                                "Base": "independent",
                            },
                        }
                        for uid in (first, second)
                    },
                },
            }
        },
    }
    if legacy_children:
        script = payload["data"][sid]
        users = script.pop("UserData")
        script["SubConfigsInfo"] = {
            "UserData": {"instances": users["order"], **users["data"]}
        }
    scripts = ConfigCollection.build([BetterGIConfig])
    if legacy_children:
        # Startup converts pre-YAML documents before activating plugin types.
        payload = convert_legacy(
            {"instances": payload["order"], **payload["data"]}, scripts
        )
    path = tmp_path / "scripts.yaml"
    io.write_file(path, payload)
    config_manager.register_root(scripts, path)
    await scripts.activate()
    await config_manager.flush()
    assert [str(uid) for uid in scripts[sid].users.keys()] == [first, second]
    assert scripts[sid].users[first].Info.Base == "independent"
    assert scripts[sid].Run.AccountSwitchMethod == "BGI"
    assert scripts[sid].users[first].Info.IfQuickConfig
    assert scripts[sid].info.name == "原托管"
    config_manager.unregister_root(scripts)
    restored = ConfigCollection.build([BetterGIConfig])
    config_manager.register_root(restored, path)
    await restored.activate()
    assert [str(uid) for uid in restored[sid].users.keys()] == [first, second]
    assert restored[sid].users[second].info.name == second
