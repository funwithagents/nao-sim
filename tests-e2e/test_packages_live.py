"""Robot packages on a running nao-sim stack, on each NAOqi version: the `animations` package built
into the image, and the package store volume that keeps what a user installs over qi."""

import stat
import zipfile

from support import connect

GESTURE = "animations/Stand/Gestures/Hey_1"
UUID = "nao-sim-e2e"
MANIFEST = f"""<?xml version='1.0' encoding='UTF-8'?>
<package version="1.0.0" uuid="{UUID}">
  <names><name lang="en_US">nao-sim e2e</name></names>
</package>
"""


def make_package(path):
    """A package as `zip` on Linux writes it: 2.8's PackageManager cannot read back an entry
    without the regular-file mode bits (what `ZipFile.writestr(name, ...)` produces)."""
    info = zipfile.ZipInfo("manifest.xml", (2026, 10, 8, 0, 0, 0))
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(info, MANIFEST)


def test_animations_is_installed_at_boot(nao):
    behaviors = nao.service("ALBehaviorManager")
    assert nao.service("PackageManager").hasPackage("animations")
    assert behaviors.isBehaviorInstalled(GESTURE)
    gestures = [b for b in behaviors.getInstalledBehaviors() if "/Stand/Gestures/" in b]
    assert len(gestures) >= 224


def test_packages_survive_down_and_up(nao, tmp_path):
    pkg = tmp_path / f"{UUID}.pkg"
    make_package(pkg)
    nao.stack.copy_in(pkg, f"/tmp/{UUID}.pkg")
    pm = nao.service("PackageManager")
    assert pm.install(f"/tmp/{UUID}.pkg")
    # A system package missing from the store comes back from the image at the next boot.
    pm.removePkg("animations")
    assert not pm.hasPackage("animations")

    nao.session.close()
    nao.stack.down()
    nao.stack.up()
    nao.session = connect()

    pm = nao.service("PackageManager")
    try:
        assert pm.hasPackage(UUID)
        assert pm.hasPackage("animations")
        assert nao.service("ALBehaviorManager").isBehaviorInstalled(GESTURE)
    finally:
        pm.removePkg(UUID)
