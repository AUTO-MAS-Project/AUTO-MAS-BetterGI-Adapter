"""沿用 v5.8 维护版的中断恢复用例，安装器和安装目录均使用测试替身。"""

import hashlib
import json
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from auto_mas_core.host.services import script_install
from packaging.version import Version

from bettergi_adapter.tools import program_update as update


def pe():
    data = bytearray(134)
    data[:2] = b"MZ"
    data[60:64] = (128).to_bytes(4, "little")
    data[128:132] = b"PE\0\0"
    data[132:134] = (0x8664).to_bytes(2, "little")
    return bytes(data)


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "BetterGI"
    (root / "User").mkdir(parents=True)
    (root / "BetterGI.exe").write_bytes(pe())
    (root / "User/config.json").write_text('{"custom": true}')
    source = tmp_path / "installer.exe"
    source.write_bytes(pe())
    release = {
        "tag_name": "0.56.0",
        "assets": [
            {
                "name": "BetterGI.Install.0.56.0.exe",
                "size": source.stat().st_size,
                "digest": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ],
    }
    monkeypatch.setattr(update, "assert_idle", lambda root: None)
    version = [Version("0.55.0")]
    monkeypatch.setattr(update, "read_version", lambda root: version[0])
    monkeypatch.setattr(update, "request_release", AsyncMock(return_value=release))
    monkeypatch.setattr(
        update, "check_stable_distribution", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        update,
        "Config",
        SimpleNamespace(
            proxy=None,
            setting=SimpleNamespace(Update=SimpleNamespace(MirrorChyanCDK="")),
        ),
    )

    async def download(url, destination, **kwargs):
        shutil.copyfile(source, destination)

    monkeypatch.setattr(
        update, "download_script_package", AsyncMock(side_effect=download)
    )

    async def install(installer, path):
        assert json.loads((path / "User/config.json").read_text()) == {"custom": True}
        version[0] = Version("0.56.0")

    monkeypatch.setattr(update, "run_installer", AsyncMock(side_effect=install))
    config = SimpleNamespace(
        Update=SimpleNamespace(
            TakeoverEnabled=True, Channel="stable", MirrorChyanCDK=""
        )
    )
    return root, config, release


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["missing", "invalid_pe", "invalid_version"])
async def test_pending_install_retries_official_package_after_executable_damage(
    installation, monkeypatch, damage
):
    root, config, _ = installation
    marker = script_install.workspace(root) / "bgi-install.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"target":"0.56.0"}')
    executable = root / "BetterGI.exe"
    if damage == "missing":
        executable.unlink()
    elif damage == "invalid_pe":
        executable.write_bytes(b"partial executable")
    else:
        executable.write_bytes(pe() + b"invalid version")
    original_version = update.read_version
    original_install = update.run_installer.side_effect

    def read_actual_version(path):
        script_install.read_pe_architecture(path / "BetterGI.exe")
        if (path / "BetterGI.exe").read_bytes().endswith(b"invalid version"):
            raise ValueError("invalid product version")
        return original_version(path)

    async def reinstall(installer, path):
        executable.write_bytes(pe())
        await original_install(installer, path)

    monkeypatch.setattr(update, "read_version", read_actual_version)
    update.run_installer.side_effect = reinstall
    with script_install.installation_access(root):
        await update.update_before_run(root, config)
        await update.confirm_current_install(root)
    assert update.read_version(root) == Version("0.56.0")
    assert not marker.exists()
    assert json.loads((root / "User/config.json").read_text()) == {"custom": True}


@pytest.mark.asyncio
async def test_pending_target_prevents_downgrade_even_when_old_exe_is_readable(
    installation,
):
    root, config, _ = installation
    marker = script_install.workspace(root) / "bgi-install.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    snapshot = b'{"target":"0.57.0"}'
    marker.write_bytes(snapshot)
    with pytest.raises(script_install.InstallUnsafeError):
        await update.update_before_run(root, config)
    update.run_installer.assert_not_awaited()
    assert marker.read_bytes() == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot", [b"{}", b'{"target":null}', b'{"target":"invalid"}', b"[]"]
)
async def test_invalid_pending_identity_blocks_before_network(installation, snapshot):
    root, config, _ = installation
    marker = script_install.workspace(root) / "bgi-install.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(snapshot)
    with pytest.raises(script_install.InstallUnsafeError):
        await update.update_before_run(root, config)
    update.request_release.assert_not_awaited()
    update.run_installer.assert_not_awaited()
    assert marker.read_bytes() == snapshot


@pytest.mark.asyncio
async def test_pending_identity_change_during_download_cannot_be_overwritten(
    installation,
):
    root, config, _ = installation
    marker = script_install.workspace(root) / "bgi-install.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(b'{"target":"0.56.0"}')
    changed = b'{"target":"0.57.0"}'
    original_download = update.download_script_package.side_effect

    async def download_then_change(*args, **kwargs):
        await original_download(*args, **kwargs)
        marker.write_bytes(changed)

    update.download_script_package.side_effect = download_then_change
    with pytest.raises(script_install.InstallUnsafeError):
        await update.update_before_run(root, config)
    update.run_installer.assert_not_awaited()
    assert marker.read_bytes() == changed


@pytest.mark.asyncio
async def test_success_exit_with_invalid_executable_keeps_pending_record(installation):
    root, config, _ = installation
    original_install = update.run_installer.side_effect

    async def corrupt_after_install(installer, path):
        await original_install(installer, path)
        (path / "BetterGI.exe").write_bytes(b"invalid executable")

    update.run_installer.side_effect = corrupt_after_install
    with pytest.raises(script_install.InstallUnsafeError):
        await update.update_before_run(root, config)
    assert (script_install.workspace(root) / "bgi-install.json").exists()


@pytest.mark.asyncio
async def test_native_upgrade_during_download_is_not_downgraded(
    installation, monkeypatch
):
    root, config, _ = installation
    original_download = update.download_script_package.side_effect
    original_version = update.read_version
    upgraded = False

    def version(path):
        return Version("0.57.0") if upgraded else original_version(path)

    async def download_then_upgrade(*args, **kwargs):
        nonlocal upgraded
        await original_download(*args, **kwargs)
        upgraded = True

    monkeypatch.setattr(update, "read_version", version)
    update.download_script_package.side_effect = download_then_upgrade
    with pytest.raises(script_install.InstallUnsafeError):
        await update.update_before_run(root, config)
    update.run_installer.assert_not_awaited()
    assert update.read_version(root) == Version("0.57.0")
    assert not (script_install.workspace(root) / "bgi-install.json").exists()
