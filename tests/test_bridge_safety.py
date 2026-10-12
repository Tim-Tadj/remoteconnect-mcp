"""Bridge safety checks using Python fakes, without vendor COM or hardware."""

import sys
import os
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from remoteconnect_mcp.bridge import CEError, ControlExpertBridge


class FakeBridge(ControlExpertBridge):
    def __init__(self, **kwargs):
        self.initialised_on = None
        self.finalised_on = None
        self.finalised = threading.Event()
        super().__init__(**kwargs)

    def _init_com(self):
        self.initialised_on = threading.get_ident()

    def _uninit_com(self):
        self._proj = None
        self._app = None
        self.finalised_on = threading.get_ident()
        self.finalised.set()


class BridgeSafetyTests(unittest.TestCase):
    def bridge(self, **kwargs):
        bridge = FakeBridge(**kwargs)
        self.addCleanup(bridge.shutdown)
        return bridge

    def test_read_and_write_use_one_worker_and_balanced_lifetime(self):
        bridge = self.bridge()
        worker = bridge._run(threading.get_ident)
        self.assertNotEqual(worker, threading.get_ident())
        self.assertEqual(bridge._run(threading.get_ident), worker)
        self.assertEqual(bridge.initialised_on, worker)
        bridge.shutdown()
        self.assertTrue(bridge.finalised.wait(1))
        self.assertEqual(bridge.finalised_on, worker)
        with self.assertRaisesRegex(CEError, "shut down"):
            bridge._run(lambda: None)

    def test_real_bridge_balances_com_initialisation_on_one_thread(self):
        calls = []
        finalised = threading.Event()
        pythoncom = types.ModuleType("pythoncom")
        pythoncom.CoInitialize = lambda: calls.append(("init", threading.get_ident()))

        def uninitialise():
            calls.append(("uninit", threading.get_ident()))
            finalised.set()

        pythoncom.CoUninitialize = uninitialise
        with patch.dict(sys.modules, {"pythoncom": pythoncom}):
            bridge = ControlExpertBridge()
            self.addCleanup(bridge.shutdown)
            worker = bridge._run(threading.get_ident)
            bridge.shutdown()
            self.assertTrue(finalised.wait(1))
        self.assertEqual(calls, [("init", worker), ("uninit", worker)])

    def test_untrusted_alias_cannot_escape_temporary_directory(self):
        bridge = self.bridge()
        with tempfile.TemporaryDirectory() as directory, patch(
            "remoteconnect_mcp.bridge.tempfile.gettempdir", return_value=directory
        ):
            path = bridge._temp_path("_alias/../../outside.xml")
            self.assertEqual(os.path.dirname(path), os.path.join(directory, "control-expert-mcp"))
            self.assertNotIn("/", os.path.basename(path))
            self.assertNotIn("\\", os.path.basename(path))

    def test_nested_call_uses_target_instances_apartment(self):
        first, second = self.bridge(), self.bridge()
        first_id = first._run(threading.get_ident)
        second_id = first._run(lambda: second._run(threading.get_ident))
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(second.initialised_on, second_id)

    def test_reentrant_call_on_same_instance_does_not_deadlock(self):
        bridge = self.bridge()
        self.assertEqual(
            bridge._run(lambda: bridge._run(threading.get_ident)),
            bridge.initialised_on,
        )

    def test_thread_name_cannot_bypass_apartment(self):
        bridge = self.bridge()
        result = []
        caller = threading.Thread(
            target=lambda: result.append((threading.get_ident(), bridge._run(threading.get_ident))),
            name="ce-com-impostor",
        )
        caller.start()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertNotEqual(*result[0])

    def test_timeout_disables_future_mutations_and_reports_unknown_outcome(self):
        bridge = self.bridge(operation_timeout=0.03)
        release = threading.Event()
        mutations = []
        try:
            with self.assertRaisesRegex(CEError, "outcome is unknown"):
                bridge._run(lambda: release.wait(1))
            with self.assertRaisesRegex(CEError, "disabled"):
                bridge._run(lambda: mutations.append("mutation"))
            self.assertEqual(bridge.get_status()["worker"], "poisoned")
            self.assertEqual(mutations, [])
        finally:
            release.set()
            bridge.shutdown()
            self.assertTrue(bridge.finalised.wait(1))

    def test_queued_mutation_is_skipped_after_first_call_times_out(self):
        bridge = self.bridge(operation_timeout=0.05)
        entered, release = threading.Event(), threading.Event()
        mutations, errors = [], []

        def block():
            entered.set()
            release.wait(1)

        def call(fn):
            try:
                bridge._run(fn)
            except CEError as exc:
                errors.append(str(exc))

        first = threading.Thread(target=call, args=(block,))
        second = threading.Thread(target=call, args=(lambda: mutations.append("unsafe"),))
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        first.join(1)
        second.join(1)
        release.set()
        bridge.shutdown()
        self.assertTrue(bridge.finalised.wait(1))
        self.assertEqual(len(errors), 2)
        self.assertEqual(mutations, [])

    def test_timeout_configuration_must_be_positive_and_finite(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                FakeBridge(operation_timeout=value)

    def test_worker_releases_error_frame_locals_on_its_own_thread(self):
        bridge = self.bridge()
        released_on = []

        class TransientDispatch:
            def __del__(self):
                released_on.append(threading.get_ident())

        def fail():
            dispatch = TransientDispatch()
            raise RuntimeError("vendor failure")

        with self.assertRaisesRegex(CEError, "vendor failure") as caught:
            bridge._run(fail)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(released_on, [bridge.initialised_on])

    def test_open_and_new_refuse_to_replace_an_active_session(self):
        bridge = self.bridge()
        app = types.SimpleNamespace(ProjectClose=Mock())
        bridge._run(lambda: setattr(bridge, "_app", app))
        with patch("remoteconnect_mcp.bridge.os.path.isfile", return_value=True):
            for call in (
                lambda: bridge.open_project("project.stu"),
                lambda: bridge.new_project("CPU", "02.70"),
                lambda: bridge.new_logic_editor_project("SCADAPack47x", "context.xpdf", None),
            ):
                with self.assertRaisesRegex(CEError, "explicitly.*close_project"):
                    call()
        app.ProjectClose.assert_not_called()
        bridge.close_project(False)

    def test_explicit_discard_closes_active_session(self):
        bridge = self.bridge()
        closed_on = []
        app = types.SimpleNamespace(ProjectClose=lambda: closed_on.append(threading.get_ident()))
        bridge._run(lambda: setattr(bridge, "_app", app))
        self.assertEqual(bridge.close_project(False), {"closed": True})
        self.assertEqual(closed_on, [bridge.initialised_on])

    def test_failed_close_retains_application_and_binding(self):
        bridge = self.bridge()
        app = types.SimpleNamespace(ProjectClose=Mock(side_effect=RuntimeError("busy")))
        bridge._run(lambda: setattr(bridge, "_app", app))
        bridge._project_path = "working.stu"
        with self.assertRaisesRegex(CEError, "remains tracked"):
            bridge.close_project(False)
        self.assertIs(bridge._app, app)
        self.assertEqual(bridge._project_path, "working.stu")
        with self.assertRaisesRegex(CEError, "already open"):
            bridge.new_project("CPU", "02.70")
        app.ProjectClose.side_effect = None
        bridge.close_project(False)

    def test_save_failure_does_not_close_project(self):
        bridge = self.bridge()
        app = types.SimpleNamespace(ProjectClose=Mock())
        bridge._run(lambda: setattr(bridge, "_app", app))
        with patch.object(bridge, "_do_save_project", side_effect=CEError("disk full")):
            with self.assertRaisesRegex(CEError, "disk full"):
                bridge.close_project(True)
        app.ProjectClose.assert_not_called()
        bridge.close_project(False)

    def test_shutdown_never_calls_projectclose_for_unsaved_changes(self):
        bridge = self.bridge()
        app = types.SimpleNamespace(ProjectClose=Mock())
        bridge._run(lambda: setattr(bridge, "_app", app))
        with patch.object(bridge, "_project", return_value=types.SimpleNamespace(IsModified=lambda: True)):
            with self.assertLogs("remoteconnect_mcp.bridge", level="WARNING"):
                bridge.shutdown()
        self.assertTrue(bridge.finalised.wait(1))
        app.ProjectClose.assert_not_called()

    def test_read_operations_do_not_reserve_write_access(self):
        bridge = self.bridge()
        tokens = []
        project = object()
        ole = types.SimpleNamespace(
            GetIDsOfNames=lambda *args: 1,
            Invoke=lambda *args: tokens.append(args[-1]) or project,
        )
        bridge._run(lambda: setattr(bridge, "_app", types.SimpleNamespace(_oleobj_=ole)))
        pythoncom = types.ModuleType("pythoncom")
        pythoncom.DISPATCH_PROPERTYGET = 2
        win32com = types.ModuleType("win32com")
        client = types.ModuleType("win32com.client")
        client.Dispatch = lambda value: value
        win32com.client = client
        with patch.dict(sys.modules, {"pythoncom": pythoncom, "win32com": win32com, "win32com.client": client}):
            self.assertIs(bridge._run(bridge._project, False), project)
            self.assertIsNone(bridge._proj)
            self.assertIs(bridge._run(bridge._project, True), project)
            self.assertIs(bridge._run(bridge._project, True), project)
        self.assertEqual(tokens, [0, 1])
        bridge._app = None

    def test_hardware_reader_only_requests_read_tokens(self):
        bridge = self.bridge()
        project = types.SimpleNamespace(Configuration=types.SimpleNamespace())
        with patch.object(bridge, "_project", return_value=project) as project_lookup, patch.object(
            bridge, "_qi", side_effect=lambda value, interface: value
        ), patch.object(bridge, "_wrap", side_effect=lambda value: value), patch.object(
            bridge, "_get_prop", return_value=[]
        ), patch.object(bridge, "_iter_qi", return_value=[]):
            bridge.get_hardware()
        self.assertEqual([call.kwargs for call in project_lookup.call_args_list], [{"write": False}, {"write": False}])

    def test_failed_rollback_reports_failure_and_preserves_recovery_exports(self):
        bridge = self.bridge()
        original = types.SimpleNamespace(ProjectClose=Mock())
        modified = types.SimpleNamespace(
            ImportProject=Mock(side_effect=RuntimeError("invalid edit")), ProjectClose=Mock()
        )
        rollback = types.SimpleNamespace(
            ImportProject=Mock(side_effect=RuntimeError("restore rejected")), ProjectClose=Mock()
        )
        bridge._run(lambda: setattr(bridge, "_app", original))
        with patch.object(bridge, "_broker", return_value=object()), patch.object(
            bridge, "_new_native_application", side_effect=[modified, rollback]
        ):
            with self.assertRaisesRegex(CEError, "has not been restored"):
                bridge._run(bridge._reimport_zef, "edited.zef", "original.zef", "working.stu", "Restored: {error}")
        self.assertEqual(bridge._recovery_archives, {"edited.zef", "original.zef"})
        self.assertIs(bridge._app, rollback)
        original.ProjectClose.assert_called_once()
        modified.ProjectClose.assert_called_once()
        bridge.close_project(False)


if __name__ == "__main__":
    unittest.main()
