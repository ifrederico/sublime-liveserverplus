"""Tests for the Sublime-facing layer: ServerManager, status bar, settings
snapshot, Markdown scroll-sync polling and ignore handling.

``ServerManager.py`` and ``LiveServerPlus.py`` use package-relative imports,
so they are loaded here as members of a throwaway package rooted at the repo
(``_lsp_editor_pkg``). That package has its own copy of ``liveserverplus_lib``;
every test below uses that copy so class-level state is shared correctly.
"""
import heapq
import importlib
import itertools
import json
import os
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sublime_stub import REPO_ROOT, fake_sublime  # noqa: E402  (installs the stub)


# ---------------------------------------------------------------------------
# Loading the plugin modules
# ---------------------------------------------------------------------------
PACKAGE = "_lsp_editor_pkg"


def _install_fake_sublime_plugin():
    if "sublime_plugin" in sys.modules:
        return

    module = types.ModuleType("sublime_plugin")

    class WindowCommand:
        def __init__(self, window):
            self.window = window

    class TextCommand:
        def __init__(self, view):
            self.view = view

    class EventListener:
        pass

    class ViewEventListener:
        def __init__(self, view):
            self.view = view

    module.WindowCommand = WindowCommand
    module.TextCommand = TextCommand
    module.EventListener = EventListener
    module.ViewEventListener = ViewEventListener
    sys.modules["sublime_plugin"] = module


def load(name):
    """Import ``name`` (e.g. ``ServerManager``) from the throwaway package."""
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(REPO_ROOT)]
        sys.modules[PACKAGE] = package
    _install_fake_sublime_plugin()
    with warnings.catch_warnings():
        # Same filter LiveServerPlus.py installs before watchdog is imported.
        warnings.filterwarnings("ignore", message="Failed to import fsevents")
        return importlib.import_module(PACKAGE + "." + name)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeLoop:
    """Main-thread timer queue on a virtual clock, plus a worker queue."""

    def __init__(self):
        self.now = 0
        self._timers = []
        self._seq = itertools.count()
        self.worker = []
        self.scheduled = []  # delays passed to set_timeout, in call order

    def set_timeout(self, callback, delay=0):
        delay = max(0, delay or 0)
        self.scheduled.append(delay)
        heapq.heappush(self._timers, (self.now + delay, next(self._seq), callback))

    def set_timeout_async(self, callback, delay=0):
        self.worker.append(callback)

    def run_worker(self):
        while self.worker:
            self.worker.pop(0)()

    def advance(self, ms=0):
        end = self.now + ms
        while self._timers and self._timers[0][0] <= end:
            due, _, callback = heapq.heappop(self._timers)
            self.now = max(self.now, due)
            callback()
        self.now = end

    def settle(self):
        """Run the worker and every zero-delay main-thread callback."""
        while True:
            self.run_worker()
            before = len(self._timers)
            self.advance(0)
            if not self.worker and len(self._timers) == before:
                return

    def pending_delays(self):
        return sorted(due - self.now for due, _, _ in self._timers)


class RecordingSettings:
    """Stands in for the live object ``sublime.load_settings`` returns."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.callbacks = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        # Sublime may call on_change listeners for set() as well as when the
        # saved file is reloaded; model the noisier of the two.
        self.values[key] = value
        self.fire()

    def add_on_change(self, key, callback):
        self.callbacks.setdefault(key, []).append(callback)

    def clear_on_change(self, key):
        self.callbacks.pop(key, None)

    def fire(self):
        for callbacks in list(self.callbacks.values()):
            for callback in list(callbacks):
                callback()

    def callback_count(self):
        return sum(len(callbacks) for callbacks in self.callbacks.values())


class FakeView:
    _ids = itertools.count(1)

    def __init__(self, file_name=None, syntax="Packages/Markdown/Markdown.sublime-syntax"):
        self._id = next(self._ids)
        self._file_name = file_name
        self._window = None
        self._settings = {"syntax": syntax}
        self.statuses = {}
        self.viewport = (0.0, 0.0)
        self.layout_height = 1000.0
        self.viewport_height = 500.0

    def id(self):
        return self._id

    def window(self):
        return self._window

    def file_name(self):
        return self._file_name

    def is_loading(self):
        return False

    def settings(self):
        return self._settings

    def set_status(self, key, text):
        self.statuses[key] = text

    def erase_status(self, key):
        self.statuses.pop(key, None)

    def viewport_position(self):
        return self.viewport

    def layout_extent(self):
        return (0.0, self.layout_height)

    def viewport_extent(self):
        return (0.0, self.viewport_height)

    def set_viewport_position(self, position, animate=True):
        self.viewport = position


class FakeWindow:
    def __init__(self, views=()):
        self._views = []
        self.active = None
        self.messages = []
        for view in views:
            self.add(view)

    def add(self, view):
        view._window = self
        self._views.append(view)
        if self.active is None:
            self.active = view
        return view

    def views(self):
        return list(self._views)

    def active_view(self):
        return self.active

    def status_message(self, message):
        self.messages.append(message)

    def project_data(self):
        return {}


class PatchMixin:
    def patch(self, obj, name, value):
        original = getattr(obj, name)
        self.addCleanup(setattr, obj, name, original)
        setattr(obj, name, value)

    def use_loop(self):
        loop = FakeLoop()
        self.patch(fake_sublime, "set_timeout", loop.set_timeout)
        self.patch(fake_sublime, "set_timeout_async", loop.set_timeout_async)
        return loop


# ---------------------------------------------------------------------------
# Item 8: stop/restart choreography
# ---------------------------------------------------------------------------
class FakeServer:
    """Records the lifecycle calls ServerManager makes on a Server."""

    log = []
    instances = []
    stop_delay = 0.0

    def __init__(self, folders):
        settings_module = load("liveserverplus_lib.settings")
        self.folders = list(folders)
        self.settings = settings_module.ServerSettings()
        self.status = types.SimpleNamespace(
            updates=[],
            refreshed=0,
        )
        self.status.update = lambda state, *args, **kwargs: self.status.updates.append(state)
        self.status.refresh = self._count_refresh
        self._alive = False
        FakeServer.instances.append(self)
        self.number = len(FakeServer.instances)
        FakeServer.log.append(("init", self.number))

    def _count_refresh(self):
        self.status.refreshed += 1

    def start(self):
        self._alive = True
        FakeServer.log.append(("start", self.number))

    def is_alive(self):
        return self._alive

    def stop(self):
        FakeServer.log.append(("stop-begin", self.number))
        if FakeServer.stop_delay:
            time.sleep(FakeServer.stop_delay)
        self._alive = False
        FakeServer.log.append(("stop-end", self.number))


class ManagerTestCase(PatchMixin, unittest.TestCase):
    def setUp(self):
        self.sm = load("ServerManager")
        self.settings_module = load("liveserverplus_lib.settings")
        FakeServer.log = []
        FakeServer.instances = []
        FakeServer.stop_delay = 0.0
        self.patch(self.sm, "Server", FakeServer)
        self.patch(self.settings_module.ServerSettings, "_global_ephemeral_port", None)
        self.store = RecordingSettings({"port": 5500})
        self.patch(fake_sublime, "load_settings", lambda name: self.store)
        self.manager = self.sm.ServerManager()


class RestartTests(ManagerTestCase):
    def test_start_waits_until_old_server_stop_returned(self):
        loop = self.use_loop()
        self.manager.start(["/site"])
        done = []

        self.manager.restart(["/site"], on_done=done.append)

        # The old server is only scheduled to stop; nothing new yet.
        self.assertEqual(FakeServer.log, [("init", 1), ("start", 1)])
        loop.run_worker()
        self.assertEqual(FakeServer.log[-1], ("stop-end", 1))
        # on_done is queued for the main thread, not run on the worker.
        self.assertEqual(len(FakeServer.instances), 1)
        loop.advance(0)

        self.assertEqual(FakeServer.log, [
            ("init", 1), ("start", 1),
            ("stop-begin", 1), ("stop-end", 1),
            ("init", 2), ("start", 2),
        ])
        self.assertEqual(done, [True])
        self.assertIs(self.manager.getServer(), FakeServer.instances[1])

    def test_restart_with_real_worker_thread_does_not_deadlock(self):
        main_thread_queue = queue.Queue()
        self.patch(fake_sublime, "set_timeout", lambda cb, delay=0: main_thread_queue.put(cb))
        self.patch(
            fake_sublime, "set_timeout_async",
            lambda cb, delay=0: threading.Thread(target=cb, daemon=True).start(),
        )
        FakeServer.stop_delay = 0.2
        self.manager.start(["/site"])
        done = []

        caller = threading.Thread(
            target=self.manager.restart, args=(["/site"],),
            kwargs={"on_done": done.append}, daemon=True,
        )
        caller.start()
        caller.join(2)
        self.assertFalse(caller.is_alive(), "restart() blocked")
        self.assertEqual(len(FakeServer.instances), 1, "started before the old server stopped")

        on_done = main_thread_queue.get(timeout=2)
        self.assertEqual(FakeServer.log[-1], ("stop-end", 1))
        self.assertEqual(len(FakeServer.instances), 1)
        on_done()

        self.assertEqual(done, [True])
        self.assertEqual(FakeServer.log[-2:], [("init", 2), ("start", 2)])

    def test_restart_does_not_deadlock_when_callbacks_run_inline(self):
        """The stub runs zero-delay callbacks inline, i.e. inside stop()."""
        inline = lambda cb, delay=0: None if delay else cb()  # noqa: E731
        self.patch(fake_sublime, "set_timeout", inline)
        self.patch(fake_sublime, "set_timeout_async", inline)
        self.manager.start(["/site"])
        done = []

        caller = threading.Thread(
            target=self.manager.restart, args=(["/site"],),
            kwargs={"on_done": done.append}, daemon=True,
        )
        caller.start()
        caller.join(2)

        self.assertFalse(caller.is_alive(), "restart() deadlocked")
        self.assertEqual(done, [True])

    def test_restart_starts_directly_when_nothing_runs(self):
        self.use_loop()
        done = []

        self.manager.restart(["/site"], on_done=done.append)

        self.assertEqual(done, [True])
        self.assertEqual(FakeServer.log, [("init", 1), ("start", 1)])

    def test_stop_without_server_returns_false_and_skips_on_done(self):
        loop = self.use_loop()
        done = []

        self.assertFalse(self.manager.stop(on_done=lambda: done.append(True)))
        loop.settle()

        self.assertEqual(done, [])

    def test_start_keeps_already_running_guard(self):
        self.use_loop()
        self.assertTrue(self.manager.start(["/site"]))
        self.assertFalse(self.manager.start(["/other"]))
        self.assertEqual(len(FakeServer.instances), 1)


# ---------------------------------------------------------------------------
# Item 9: settings snapshot and the restart watcher
# ---------------------------------------------------------------------------
class SettingsSnapshotTests(PatchMixin, unittest.TestCase):
    def setUp(self):
        self.settings_module = load("liveserverplus_lib.settings")
        self.patch(self.settings_module.ServerSettings, "_global_ephemeral_port", None)
        self.store = RecordingSettings({"port": 5500})
        self.patch(fake_sublime, "load_settings", lambda name: self.store)

    def test_values_are_a_snapshot(self):
        settings = self.settings_module.ServerSettings()
        self.store.values.update(port=5600, liveReload=True, fullReload=True)

        self.assertEqual(settings.port, 5500)
        self.assertFalse(settings.liveReload)
        self.assertFalse(settings.fullReload)
        self.assertEqual(settings.changed_restart_keys(), ["port", "liveReload"])

    def test_refresh_applies_live_keys_only(self):
        settings = self.settings_module.ServerSettings()
        self.store.values.update(port=5600, fullReload=True, wait=250, markdownScrollSync="sync")

        settings.refresh()

        self.assertTrue(settings.fullReload)
        self.assertEqual(settings.waitTimeMs, 250)
        self.assertEqual(settings.markdownScrollSyncMode, "sync")
        self.assertEqual(settings.port, 5500)
        self.assertEqual(settings.changed_restart_keys(), ["port"])

    def test_every_restart_key_is_compared(self):
        settings = self.settings_module.ServerSettings()
        self.store.values.update(
            port=5600, host="0.0.0.0", useLocalIp=True, liveReload=True,
            maxThreads=8, maxWatchedDirs=99, ignoreFiles=["dist"],
            ignoreDirs=["vendor"], useWebExt=True,
        )

        self.assertEqual(
            sorted(settings.changed_restart_keys()),
            sorted(self.settings_module.RESTART_KEYS),
        )

    def test_unchanged_file_reports_no_restart_keys(self):
        settings = self.settings_module.ServerSettings()
        self.store.values.update(showInfoMessages=False, openBrowser=False)

        self.assertEqual(settings.changed_restart_keys(), [])

    def test_project_overrides_are_captured_at_start(self):
        window = FakeWindow()
        window.project_data = lambda: {"liveserverplus": {"port": 6000}}
        self.patch(fake_sublime, "active_window", lambda: window)
        settings = self.settings_module.ServerSettings()

        # Another window (without overrides) becomes active.
        self.patch(fake_sublime, "active_window", lambda: None)

        self.assertEqual(settings.port, 6000)
        self.assertEqual(settings.changed_restart_keys(), [])

    def test_changed_port_is_used_by_the_next_server(self):
        """The port used to stick for the whole session after the first start."""
        self.assertEqual(self.settings_module.ServerSettings().port, 5500)
        self.store.values["port"] = 5600

        self.assertEqual(self.settings_module.ServerSettings().port, 5600)

    def test_random_port_is_kept_across_restarts(self):
        self.store.values["port"] = 0
        first = self.settings_module.ServerSettings().port

        self.assertEqual(self.settings_module.ServerSettings().port, first)

    def test_changed_keys_helper(self):
        changed_keys = self.settings_module.changed_keys
        self.assertEqual(changed_keys({"a": 1, "b": [1]}, {"a": 1, "b": [2]}, ("a", "b")), ["b"])
        self.assertEqual(changed_keys({}, {}, ("a",)), [])


class SettingsWatcherTests(ManagerTestCase):
    KEY = "liveserverplus_restart_watch"

    def setUp(self):
        super().setUp()
        self.loop = self.use_loop()

    def test_one_watcher_while_running_and_none_after_stop(self):
        self.manager.start(["/site"])
        self.assertEqual(self.store.callback_count(), 1)

        self.manager.stop()
        self.loop.settle()

        self.assertEqual(self.store.callback_count(), 0)

    def test_restart_key_change_restarts_once_after_debounce(self):
        self.manager.start(["/site"])
        self.store.values["port"] = 5600

        for _ in range(3):  # Sublime may fire more than once per save
            self.store.fire()
            self.loop.advance(100)
        self.loop.advance(199)
        self.assertEqual(len(FakeServer.instances), 1)

        self.loop.advance(1)
        self.loop.settle()

        self.assertEqual(len(FakeServer.instances), 2)
        self.assertEqual(FakeServer.instances[0].status.updates, ["restarting"])
        self.assertEqual(self.manager.getServer().settings.port, 5600)
        self.assertEqual(self.store.callback_count(), 1)

    def test_watcher_restart_does_not_loop(self):
        self.manager.start(["/site"])
        self.store.values["liveReload"] = True
        self.store.fire()
        self.loop.advance(300)
        self.loop.settle()
        self.assertEqual(len(FakeServer.instances), 2)

        self.store.fire()  # e.g. Sublime reloading the saved file
        self.loop.advance(5000)
        self.loop.settle()

        self.assertEqual(len(FakeServer.instances), 2)

    def test_live_key_change_applies_without_restart(self):
        self.manager.start(["/site"])
        server = self.manager.getServer()
        self.store.values.update(fullReload=True, showOnStatusbar=False)

        self.store.fire()
        self.loop.advance(300)
        self.loop.settle()

        self.assertEqual(len(FakeServer.instances), 1)
        self.assertTrue(server.settings.fullReload)
        self.assertFalse(server.settings.showOnStatusbar)
        self.assertEqual(server.status.refreshed, 1)

    def test_command_restart_is_not_doubled_by_the_watcher(self):
        """A command writes the setting (firing the watcher), then restarts."""
        self.manager.start(["/site"])

        self.store.set("useLocalIp", True)  # fires on_change synchronously
        self.manager.restart(["/site"])
        self.loop.settle()
        self.assertEqual(len(FakeServer.instances), 2)

        self.store.fire()  # the saved file is reloaded afterwards
        self.loop.advance(1000)
        self.loop.settle()

        self.assertEqual(len(FakeServer.instances), 2)
        self.assertTrue(self.manager.getServer().settings.useLocalIp)

    def test_stop_cancels_a_pending_check(self):
        self.manager.start(["/site"])
        self.store.values["port"] = 5600
        self.store.fire()

        self.manager.stop()
        self.loop.advance(1000)
        self.loop.settle()

        self.assertEqual(len(FakeServer.instances), 1)
        self.assertIsNone(self.manager.getServer())

    def test_dead_server_is_not_restarted(self):
        self.manager.start(["/site"])
        FakeServer.instances[0]._alive = False  # e.g. the bind failed
        self.store.values["port"] = 5600
        self.store.fire()

        self.loop.advance(300)
        self.loop.settle()

        self.assertEqual(len(FakeServer.instances), 1)


# ---------------------------------------------------------------------------
# Item 10: status bar on every view of every window
# ---------------------------------------------------------------------------
class StatusTests(PatchMixin, unittest.TestCase):
    KEY = "liveserverplus"

    def setUp(self):
        self.status_module = load("liveserverplus_lib.status")
        self.ServerStatus = self.status_module.ServerStatus
        self.patch(self.ServerStatus, "_shown_text", None)
        self.loop = self.use_loop()
        self.first = FakeWindow([FakeView("/site/a.html"), FakeView("/site/b.css")])
        self.second = FakeWindow([FakeView("/other/c.html")])
        self.windows = [self.first, self.second]
        self.patch(fake_sublime, "windows", lambda: list(self.windows))
        self.settings = types.SimpleNamespace(showOnStatusbar=True, showInfoMessages=False)

    def all_views(self):
        return [view for window in self.windows for view in window.views()]

    def texts(self):
        return [view.statuses.get(self.KEY) for view in self.all_views()]

    def test_running_status_reaches_every_window(self):
        self.ServerStatus(self.settings).update("running", 5500)

        self.assertEqual(self.texts(), ["[Ø:5500]"] * 3)
        self.assertEqual(self.ServerStatus.current_text(), "[Ø:5500]")

    def test_views_opened_later_get_the_current_status(self):
        self.ServerStatus(self.settings).update("running", 5500)
        late = self.first.add(FakeView("/site/new.html"))
        third = FakeWindow([FakeView()])
        self.windows.append(third)

        self.ServerStatus.apply_to_view(late)
        self.ServerStatus.apply_to_view(third.views()[0])

        self.assertEqual(late.statuses[self.KEY], "[Ø:5500]")
        self.assertEqual(third.views()[0].statuses[self.KEY], "[Ø:5500]")

    def test_clear_reaches_every_window_and_late_views(self):
        status = self.ServerStatus(self.settings)
        status.update("running", 5500)
        stale = FakeView()
        stale.set_status(self.KEY, "[Ø:5500]")

        status.clear()
        self.ServerStatus.apply_to_view(stale)

        self.assertEqual(self.texts(), [None] * 3)
        self.assertIsNone(self.ServerStatus.current_text())
        self.assertNotIn(self.KEY, stale.statuses)

    def test_spinner_frames_reach_late_views(self):
        status = self.ServerStatus(self.settings)
        status.update("starting")
        first_frame = self.ServerStatus.current_text()
        self.assertTrue(first_frame.endswith("Starting server"))
        self.assertEqual(self.texts(), [first_frame] * 3)

        self.loop.advance(150)
        second_frame = self.ServerStatus.current_text()
        self.assertNotEqual(first_frame, second_frame)
        late = self.second.add(FakeView())
        self.ServerStatus.apply_to_view(late)
        self.assertEqual(late.statuses[self.KEY], second_frame)

        status.update("running", 5500)
        self.loop.advance(1000)
        self.assertEqual(self.texts(), ["[Ø:5500]"] * 4)  # includes the late view

    def test_stopped_message_is_cleared_after_two_seconds(self):
        status = self.ServerStatus(self.settings)
        status.update("stopped")
        self.assertEqual(self.texts(), ["[X] Server stopped"] * 3)

        self.loop.advance(2000)

        self.assertEqual(self.texts(), [None] * 3)

    def test_old_server_does_not_clear_the_next_servers_status(self):
        old = self.ServerStatus(self.settings)
        old.update("stopped")
        self.ServerStatus(self.settings).update("running", 5501)

        self.loop.advance(2000)

        self.assertEqual(self.texts(), ["[Ø:5501]"] * 3)

    def test_window_without_views_gets_a_status_message(self):
        empty = FakeWindow()
        self.windows.append(empty)

        self.ServerStatus(self.settings).update("running", 5500)

        self.assertEqual(empty.messages, ["[Ø:5500]"])

    def test_refresh_follows_show_on_statusbar(self):
        status = self.ServerStatus(self.settings)
        status.update("running", 5500)

        self.settings.showOnStatusbar = False
        status.refresh()
        self.assertEqual(self.texts(), [None] * 3)

        self.settings.showOnStatusbar = True
        status.refresh()
        self.assertEqual(self.texts(), ["[Ø:5500]"] * 3)

    def test_event_listener_applies_status_on_activated_load_and_new(self):
        plugin = load("LiveServerPlus")
        self.assertIs(plugin.ServerStatus, self.ServerStatus)
        self.ServerStatus(self.settings).update("running", 5500)
        listener = plugin.LiveServerStatusListener()

        for hook in ("on_activated", "on_load", "on_new"):
            view = FakeView()
            getattr(listener, hook)(view)
            self.assertEqual(view.statuses.get(self.KEY), "[Ø:5500]", hook)


# ---------------------------------------------------------------------------
# Item 11: Markdown scroll sync polling
# ---------------------------------------------------------------------------
class FakeScrollManager:
    def __init__(self, running=True):
        self.running = running
        self.messages = []
        self.server = types.SimpleNamespace(
            folders=["/site"],
            settings=types.SimpleNamespace(markdownScrollSyncMode="editor"),
        )

    def isRunning(self):
        return self.running

    def getServer(self):
        return self.server if self.running else None

    def broadcastMessage(self, message):
        self.messages.append(message)
        return True


class ScrollSyncPollingTests(PatchMixin, unittest.TestCase):
    def setUp(self):
        self.plugin = load("LiveServerPlus")
        self.sm = load("ServerManager")
        self.loop = self.use_loop()
        self.manager = FakeScrollManager(running=True)
        self.patch(self.sm.ServerManager, "_instance", self.manager)
        self.patch(self.plugin, "time", types.SimpleNamespace(time=lambda: 1000 + self.loop.now / 1000.0))
        self.addCleanup(self.plugin._SCROLL_SYNC_LISTENERS.clear)
        self.window = FakeWindow()
        self.patch(fake_sublime, "active_window", lambda: self.window)

    def make(self, name="doc.md", active=False):
        view = self.window.add(FakeView("/site/" + name))
        if active:
            self.window.active = view
        return view, self.plugin.MarkdownScrollSyncListener(view)

    def test_inactive_view_does_not_poll(self):
        self.window.add(FakeView("/site/index.html"))  # the active view
        self.make()

        self.assertEqual(self.loop.scheduled, [])

    def test_only_the_active_view_polls(self):
        self.window.add(FakeView("/site/index.html"))
        listeners = [self.make("doc%d.md" % i)[1] for i in range(20)]
        self.window.active = listeners[0].view
        listeners[0].on_activated()

        self.loop.advance(1200)

        self.assertEqual(len(self.loop.scheduled), 11)  # 120 ms ticks, one view
        self.assertEqual(self.loop.pending_delays(), [120])

    def test_already_active_view_starts_polling_on_creation(self):
        self.make(active=True)

        self.assertEqual(self.loop.pending_delays(), [120])

    def test_deactivation_stops_polling(self):
        view, listener = self.make(active=True)
        other = self.window.add(FakeView("/site/index.html"))

        self.window.active = other
        listener.on_deactivated()
        self.loop.advance(1000)

        self.assertEqual(self.loop.pending_delays(), [])

    def test_switching_away_without_deactivation_event_stops_at_next_tick(self):
        self.make(active=True)
        self.window.active = self.window.add(FakeView("/site/index.html"))

        self.loop.advance(120)

        self.assertEqual(self.loop.pending_delays(), [])

    def test_app_losing_focus_keeps_polling(self):
        """Still the active view: scrolling the unfocused editor must sync."""
        view, listener = self.make(active=True)

        listener.on_deactivated()
        self.loop.advance(120)

        self.assertEqual(self.loop.pending_delays(), [120])

    def test_reactivation_does_not_start_a_second_chain(self):
        view, listener = self.make(active=True)
        other = self.window.add(FakeView("/site/index.html"))
        for _ in range(3):
            self.window.active = other
            listener.on_deactivated()
            self.window.active = view
            listener.on_activated()
            listener.on_activated()  # repeated events must not stack chains

        self.loop.advance(600)

        self.assertEqual(self.loop.pending_delays(), [120])

    def test_close_stops_polling_and_unregisters(self):
        view, listener = self.make(active=True)

        listener.on_close()
        self.loop.advance(1000)

        self.assertEqual(self.loop.pending_delays(), [])
        self.assertNotIn(view.id(), self.plugin._SCROLL_SYNC_LISTENERS)

    def test_plugin_unload_ends_polling(self):
        self.manager.running = False
        self.make(active=True)

        self.plugin.plugin_unloaded()
        self.loop.advance(5000)

        self.assertEqual(self.loop.pending_delays(), [])

    def test_backs_off_while_no_server_runs(self):
        self.manager.running = False
        self.make(active=True)

        self.loop.advance(120)
        self.assertEqual(self.loop.pending_delays(), [1000])
        self.loop.advance(3000)
        self.assertEqual(self.manager.messages, [])

        self.manager.running = True
        self.loop.advance(1000)
        self.assertEqual(self.loop.pending_delays(), [120])

    def test_sync_payload_and_thresholds_are_unchanged(self):
        view, listener = self.make(active=True)
        view.viewport = (0.0, 250.0)

        self.loop.advance(120)
        self.assertEqual(self.manager.messages, [json.dumps(
            {"type": "markdown-scroll", "path": "/doc.md", "ratio": 0.5, "source": "editor"},
            separators=(",", ":"),
        )])

        view.viewport = (0.0, 252.0)  # below MIN_RATIO_DELTA
        self.loop.advance(240)
        self.assertEqual(len(self.manager.messages), 1)

        view.viewport = (0.0, 500.0)
        self.loop.advance(120)
        self.assertEqual(len(self.manager.messages), 2)
        self.assertEqual(json.loads(self.manager.messages[-1])["ratio"], 1.0)


# ---------------------------------------------------------------------------
# Item 12: ignoreFiles uses the gitignore-style matcher everywhere
# ---------------------------------------------------------------------------
DEFAULT_IGNORES = ["**/node_modules/**", "**/.git/**", "**/__pycache__/**"]


class FakeObserver:
    def __init__(self):
        self.paths = []

    def schedule(self, event_handler, path, recursive=False):
        self.paths.append(path)


class IgnoreUsageTests(PatchMixin, unittest.TestCase):
    def setUp(self):
        self.file_watcher = load("liveserverplus_lib.file_watcher")
        self.patch(self.file_watcher, "Observer", FakeObserver)

    def make_watcher(self, folder, patterns):
        settings = types.SimpleNamespace(
            ignorePatterns=patterns,
            ignoreDirs=[],
            allowedFileTypes=[".html", ".js"],
            maxWatchedDirs=50,
        )
        return self.file_watcher.FileWatcher([folder], lambda path: None, settings)

    def test_watcher_ignores_nested_files(self):
        watcher = self.make_watcher("/site", DEFAULT_IGNORES)

        self.assertTrue(watcher._matches_ignore("/site/node_modules/pkg/dist/foo.js"))
        self.assertTrue(watcher._matches_ignore("/site/node_modules/foo.js"))
        self.assertFalse(watcher._matches_ignore("/site/src/app.js"))

    def test_watcher_prunes_directories_matching_ignore_patterns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "site")
            for rel in ("index.html", "node_modules/pkg/dist/a.js",
                        "build/out/b.html", "src/c.js"):
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("x", encoding="utf-8")

            watcher = self.make_watcher(str(root), DEFAULT_IGNORES + ["build"])
            watched = [os.path.relpath(p, str(root)) for p in watcher.observer.paths]

        self.assertEqual(sorted(watched), [".", "src"])

    def test_live_reload_listener_uses_glob_semantics(self):
        plugin = load("LiveServerPlus")
        manager = types.SimpleNamespace(isFileAllowed=lambda path: True)
        server = types.SimpleNamespace(settings=types.SimpleNamespace(ignorePatterns=DEFAULT_IGNORES))
        listener = plugin.LiveServerPlusListener()

        self.assertFalse(listener._should_trigger(manager, server, "/site/node_modules/pkg/dist/a.js"))
        self.assertTrue(listener._should_trigger(manager, server, "/site/src/a.js"))
        self.assertFalse(hasattr(plugin, "_matches_ignore_patterns"))


if __name__ == "__main__":
    unittest.main()
