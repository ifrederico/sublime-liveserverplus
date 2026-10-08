"""Fake ``sublime`` module for running the plugin outside the editor.

Import this before anything from ``liveserverplus_lib``; it installs the
stub into ``sys.modules`` and puts the vendored packages on ``sys.path``.

``set_timeout`` / ``set_timeout_async`` run a zero-delay callback
immediately and drop delayed ones, so code that reschedules itself (the
status-bar spinner) cannot recurse forever under the stub.
"""
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_PATH = REPO_ROOT / "liveserverplus_lib" / "vendor"
PACKAGE_PREFIX = "Packages/LiveServerPlus/"

for entry in (str(VENDOR_PATH), str(REPO_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


class FakeSettings:
    """Settings object that answers from ``values`` and otherwise defaults."""

    values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def add_on_change(self, key, callback):
        pass

    def clear_on_change(self, key):
        pass


def _resource_file(resource_path):
    if not resource_path.startswith(PACKAGE_PREFIX):
        raise FileNotFoundError(resource_path)
    return REPO_ROOT / resource_path[len(PACKAGE_PREFIX):]


def load_resource(resource_path):
    return _resource_file(resource_path).read_text(encoding="utf-8")


def load_binary_resource(resource_path):
    return _resource_file(resource_path).read_bytes()


def _timeout(callback, delay=0):
    if not delay:
        callback()


fake_sublime = types.SimpleNamespace(
    load_settings=lambda name: FakeSettings(),
    save_settings=lambda name: None,
    load_resource=load_resource,
    load_binary_resource=load_binary_resource,
    set_timeout=_timeout,
    set_timeout_async=_timeout,
    status_message=lambda message: None,
    error_message=lambda message: None,
    message_dialog=lambda message: None,
    ok_cancel_dialog=lambda *args, **kwargs: False,
    active_window=lambda: None,
    windows=lambda: [],
    packages_path=lambda: str(REPO_ROOT.parent),
    version=lambda: "4200",
    OP_EQUAL=0,
    OP_NOT_EQUAL=1,
)

sys.modules.setdefault("sublime", fake_sublime)
