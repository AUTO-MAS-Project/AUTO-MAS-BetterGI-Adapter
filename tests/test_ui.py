"""验证 BetterGI 三层编辑块、宿主沙箱和分发包。"""

from html.parser import HTMLParser
from pathlib import Path
from shutil import copy2, copytree
from zipfile import ZipFile

from app.api import plugin_router
from app.api._config_editors import config_detail_ui
from app.api.scripts import router as scripts_router
from app.config import ConfigCollection, config_manager
from app.core import Config, Plugin
from app.core.i18n import I18nManager
from app.models.config import PluginRecord, PluginRegistryCollection
from app.models.schema import DeclarativeBlockOut, HostBlockOut, PluginBlockOut
from app.plugin.calls import CallGate
from app.plugin.frontend import MountedFrontend
from app.plugin.http import HttpRegistry
from app.plugin.types import PluginState
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import bettergi_adapter
from bettergi_adapter.config import BetterGIConfig
from bettergi_adapter.plugin import Plugin as Adapter

PACKAGE = Path(bettergi_adapter.__file__).resolve().parent
SOURCE = Path(__file__).resolve().parents[1]
NAME = "bettergi_adapter"


class PanelAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.files = {"script-src": [], "style-src": []}

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        assert tag != "style"
        assert not any(name == "style" or name.startswith("on") for name in fields)
        if tag == "script":
            assert fields.get("type") != "module" and "crossorigin" not in fields
            assert fields["src"].startswith("./")
            if fields["src"] != "./_host/panel-sdk.js":
                assert "defer" in fields
            self.files["script-src"].append(fields["src"][2:])
        if tag == "link" and fields.get("rel") == "stylesheet":
            assert fields["href"].startswith("./")
            self.files["style-src"].append(fields["href"][2:])


async def mount_frontend(monkeypatch):
    registry = PluginRegistryCollection.build()
    await registry.activate()
    record_id = registry.add(
        PluginRecord,
        payload={"info": {"plugin_name": NAME, "state": PluginState.ENABLED}},
    )
    await registry.commit()
    record = registry[record_id]
    record._plugin_cls = Adapter
    record._plugin = Adapter()
    monkeypatch.setattr(Config, "plugin_registry", registry)
    monkeypatch.setattr(Plugin, "script_types", {record.uid: Adapter.decl})

    gate = CallGate()
    monkeypatch.setitem(Plugin._calls, record.uid, gate)
    frontend = MountedFrontend.load(
        PACKAGE, NAME, "BetterGI", None, gate, block_pages={"user"}
    )
    assert frontend is not None
    assert frontend.diagnostics == []
    assert frontend.block_pages == {"user"}

    app = FastAPI()
    app.include_router(plugin_router)
    app.include_router(scripts_router)
    http = HttpRegistry()
    monkeypatch.setattr(Plugin, "http", http)
    http.bind_app(app)
    http.mount(NAME, [], router=Adapter.api_router, frontend=frontend, gate=gate)
    return app, frontend


async def test_built_panel_served_under_host_csp(monkeypatch):
    app, frontend = await mount_frontend(monkeypatch)
    root = f"/api/plugin/{NAME}/ui/{frontend.revision}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"{root}/user.html")
        assert response.status_code == 200
        policy = dict(
            directive.split(" ", 1)
            for directive in response.headers["Content-Security-Policy"].split("; ")
        )
        assert policy["default-src"] == "'none'"
        assert policy["sandbox"] == "allow-scripts allow-forms"
        assert all(
            source.startswith(f"http://test{root}/")
            for source in policy["connect-src"].split()
        )
        assets = PanelAssets()
        assets.feed(response.text)
        assert assets.files == {
            "script-src": ["_host/panel-sdk.js", "assets/user.js"],
            "style-src": ["_host/panel-base.css", "assets/user.css"],
        }
        for directive, mime in (
            ("script-src", "text/javascript"),
            ("style-src", "text/css"),
        ):
            assert "'unsafe-inline'" not in policy[directive].split()
            for path in assets.files[directive]:
                target = f"http://test{root}/{path}"
                assert target in policy[directive].split()
                asset = await client.get(target)
                assert asset.status_code == 200
                assert asset.headers["Content-Type"].startswith(mime)

    manager = I18nManager(Config.resource_path / "i18n")
    manager.set_package_roots({NAME: PACKAGE})
    for locale in ("zh-CN", "en-US", "ja-JP"):
        messages, _ = await manager.get_messages(locale)
        panel = messages["plugins"][NAME]["panel"]["editor"]
        assert (
            panel["queue"]
            and panel["bettergiTeamConfig"]
            and panel["bettergiGameClient"]
        )


async def test_editor_blocks_and_scoped_routes(monkeypatch, tmp_path):
    scripts = ConfigCollection.build([BetterGIConfig])
    await scripts.activate()
    monkeypatch.setattr(Config, "ScriptConfig", scripts)
    monkeypatch.setitem(config_manager._collections, "ScriptConfig", scripts)
    app, frontend = await mount_frontend(monkeypatch)

    await Adapter().pre_enable()
    script_uid, script = await Config.add_script("BetterGI")
    script_id = str(script_uid)
    installation = tmp_path.with_name(f"{tmp_path.name}-installation")
    root = installation / "User" / "OneDragon"
    root.mkdir(parents=True)
    (installation / "BetterGI.exe").touch()
    await script.update(
        BetterGIConfig.model_validate({"Info": {"RootPath": installation}})
    )
    (root / "默认配置.json").write_text("{}", encoding="utf-8")

    _, script_documents = await Config.get_script(script_id)
    assert config_detail_ui(script, script_documents).blocks == [
        DeclarativeBlockOut(groups=["Info"]),
        HostBlockOut(name="game_binding"),
        DeclarativeBlockOut(groups=["Run", "Game", "Update"]),
    ]

    user_uid, user = await Config.add_user(script_id)
    user_id = str(user_uid)
    _, documents = await Config.get_user(script_id, user_id)
    ui = config_detail_ui(user, documents)
    assert ui.blocks == [
        HostBlockOut(name="config_restore"),
        HostBlockOut(name="native_session"),
        DeclarativeBlockOut(groups=["Info"]),
        PluginBlockOut(
            pageId="user",
            fallbackGroups=["Switch", "Task", "OneDragon"],
            mount=frontend.surface_mount(name=NAME, page="user"),
        ),
        DeclarativeBlockOut(groups=["Notify"]),
        HostBlockOut(name="webhooks"),
    ]
    assert [(pool.key, pool.kind) for pool in ui.backupTargets] == [
        ("mas", "user"),
        ("native", "script"),
    ]
    assert ui.nativeSession == "config"
    for pool in ui.backupTargets:
        assert (await Config.list_config_backups(script_id, user_id, pool.key))[
            "items"
        ] == []

    headers = {
        "X-Plugin-Ui-Provider": NAME,
        "X-Plugin-Ui-Activation": frontend.activation_id,
        "X-Plugin-Ui-Page": "user",
    }
    ids = {"scriptId": script_id, "userId": user_id}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        prefix = f"/api/plugin/{NAME}"
        for path in ("/api/scripts", prefix):
            result = await client.get(
                f"{path}/bettergi/one-dragon/configs", params=ids, headers=headers
            )
            assert result.status_code == result.json()["code"] == 200, result.text
            assert result.json()["data"][0]["value"] == "默认配置"
        editor = f"{prefix}/editor/user/{script_id}/{user_id}"
        context = await client.get(editor, headers=headers)
        assert context.json() == {
            "base": "independent",
            "rootConfigured": True,
            "gamePath": "",
            "plan": "",
        }

        result = await client.post(
            "/api/scripts/user/update",
            headers=headers,
            json={**ids, "data": {"OneDragon": {"PartyName": "战斗队伍"}}},
        )
        assert result.status_code == result.json()["code"] == 200, result.text
        assert user.OneDragon.PartyName == "战斗队伍"
        settings = {
            **ids,
            "configName": "MAS独立配置",
            "groupName": "自动秘境",
        }
        result = await client.post(
            f"{prefix}/bettergi/one-dragon/settings",
            headers=headers,
            json={**settings, "settings": {"DomainName": "测试秘境"}},
        )
        assert result.status_code == result.json()["code"] == 200, result.text
        reloaded = await client.get(
            f"{prefix}/bettergi/one-dragon/settings", params=settings, headers=headers
        )
        assert reloaded.json()["data"]["DomainName"] == "测试秘境"

        result = await client.post(
            "/api/scripts/user/update",
            json={**ids, "data": {"Info": {"Base": "native"}}},
        )
        assert result.status_code == result.json()["code"] == 200, result.text
        assert user.Info.IfQuickConfig is False
        assert (await client.get(editor, headers=headers)).json()["base"] == "native"


def test_wheel_contains_ui_and_locales(tmp_path, monkeypatch):
    from setuptools.build_meta import build_wheel

    sources = tmp_path / "sources"
    sources.mkdir()
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        copy2(SOURCE / filename, sources)
    copytree(SOURCE / "src" / NAME, sources / "src" / NAME)
    monkeypatch.chdir(sources)
    wheel = tmp_path / build_wheel(str(tmp_path))
    with ZipFile(wheel) as archive:
        paths = {
            f"{NAME}/ui/manifest.json",
            f"{NAME}/ui/user.html",
            f"{NAME}/ui/assets/user.js",
            f"{NAME}/ui/assets/user.css",
            *(f"{NAME}/i18n/{locale}.json" for locale in ("zh-CN", "en-US", "ja-JP")),
        }
        assets = {
            path.relative_to(sources / "src").as_posix()
            for folder in ("ui", "i18n")
            for path in (sources / "src" / NAME / folder).rglob("*")
            if path.is_file()
        }
        assert paths <= assets <= set(archive.namelist())
        for path in assets:
            assert archive.read(path) == (sources / "src" / path).read_bytes()
