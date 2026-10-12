"""Real stdio JSON-RPC checks that refuse vendor and equipment activation.

The child runs the package entry point. A safety bootstrap makes runtime,
simulator and Modbus activation fail before any vendor or network access.
On Windows the server's asynchronous event loop may require an unrestricted
test process when a filesystem sandbox prevents its local socket pair.
"""

import collections
import contextlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from mcp.types import LATEST_PROTOCOL_VERSION
from remoteconnect_mcp import __version__

from remoteconnect_mcp.tool_policy import OFFLINE_TOOLS, ONLINE_TOOLS, READ_TOOLS, SESSION_TOOLS


_CHILD_BOOTSTRAP = """
import runpy
from remoteconnect_mcp.bridge import ControlExpertBridge
from remoteconnect_mcp.modbus import ModbusClient
from remoteconnect_mcp import native_bridge

def refuse(*args, **kwargs):
    raise AssertionError("Protocol test attempted vendor or equipment activation")

ControlExpertBridge._init_com = staticmethod(refuse)
ControlExpertBridge._broker = staticmethod(refuse)
for name in (
    "start_simulator", "stop_simulator", "plc_setup_connection", "plc_connect",
    "plc_disconnect", "plc_state", "plc_transfer", "plc_command",
):
    setattr(ControlExpertBridge, name, refuse)
for name in ("connect", "disconnect", "read_one", "write_one"):
    setattr(ModbusClient, name, refuse)
native_bridge._run = refuse
native_bridge._build_bridge = refuse
from remoteconnect_mcp import server
import time

probe_order = []

@server.tool()
def protocol_slow_probe(label: str, delay: float = 0.3) -> dict:
    probe_order.append(label + ":start")
    (server.policy.write_roots[0] / "probe-started.txt").write_text(label, encoding="utf-8")
    time.sleep(delay)
    probe_order.append(label + ":end")
    return {"label": label, "order": list(probe_order)}

runpy.run_module("remoteconnect_mcp", run_name="__main__")
"""


class StdioPeer:
    """A bounded synchronous peer, including a strict stdout framing check."""

    def __init__(self, process):
        self.process = process
        self.messages = queue.Queue()
        self.stderr = collections.deque(maxlen=40)
        self.next_id = 1
        self.pending = {}
        self.readers = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for reader in self.readers:
            reader.start()

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                        raise ValueError("stdout did not contain a JSON-RPC 2.0 object")
                    self.messages.put((True, message))
                except (ValueError, TypeError) as exc:
                    self.messages.put((False, f"Invalid protocol stdout: {line[:160]!r}: {exc}"))
        finally:
            self.messages.put((False, "Server closed stdout before responding"))

    def _read_stderr(self):
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def send_request(self, method, params=None):
        request_id = self.next_id
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        return request_id

    def receive(self, request_id, *, timeout=15):
        # No tested operation activates vendor code, so a long runtime wait is
        # never appropriate. Diagnostics are limited to this child's stderr.
        deadline = time.monotonic() + timeout
        while True:
            if request_id in self.pending:
                response = self.pending.pop(request_id)
                break
            try:
                valid, response = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise AssertionError(
                    f"No stdio response for request {request_id}; child stderr: {list(self.stderr)[-8:]}"
                ) from None
            if not valid:
                raise AssertionError(f"{response}; child stderr: {list(self.stderr)[-8:]}")
            if "id" not in response:
                continue
            if response["id"] != request_id:
                if response["id"] in self.pending:
                    raise AssertionError(f"Duplicate response id: {response['id']}")
                self.pending[response["id"]] = response
                continue
            break
        if "error" in response:
            raise AssertionError(f"JSON-RPC request failed: {response['error']}")
        return response["result"]

    def request(self, method, params=None):
        return self.receive(self.send_request(method, params))

    def close(self):
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        for reader in self.readers:
            reader.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()


class MCPProtocolTests(unittest.TestCase):
    @contextlib.contextmanager
    def server(self, profile="offline", online="0"):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="mcp-protocol-") as directory:
            environment = dict(os.environ)
            environment.update({
                "CE_MCP_TOOL_PROFILE": profile,
                "CE_MCP_ENABLE_ONLINE": online,
                "CE_MCP_READ_ROOTS": directory,
                "CE_MCP_WRITE_ROOTS": directory,
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": str(repository / "src"),
                "LOCALAPPDATA": directory,
                "TEMP": directory,
                "TMP": directory,
            })
            process = subprocess.Popen(
                [sys.executable, "-u", "-c", _CHILD_BOOTSTRAP],
                cwd=repository,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            peer = StdioPeer(process)
            try:
                initialisation = peer.request("initialize", {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "remoteconnect-protocol-tests", "version": "1.0"},
                })
                self.assertEqual(initialisation["protocolVersion"], LATEST_PROTOCOL_VERSION)
                self.assertEqual(initialisation["serverInfo"]["name"], "RemoteConnect")
                self.assertEqual(initialisation["serverInfo"]["version"], __version__)
                self.assertIn("tools", initialisation["capabilities"])
                peer.notify("notifications/initialized")
                yield peer, Path(directory)
            finally:
                peer.close()

    def tools(self, peer):
        tools = {}
        parameters = {}
        while True:
            result = peer.request("tools/list", parameters)
            for tool in result["tools"]:
                self.assertNotIn(tool["name"], tools)
                tools[tool["name"]] = tool
            if not result.get("nextCursor"):
                return tools
            parameters = {"cursor": result["nextCursor"]}

    def content_text(self, result):
        return "\n".join(item.get("text", "") for item in result.get("content", []) if item.get("type") == "text")

    def test_profile_discovery_and_annotations_over_actual_stdio(self):
        for profile in ("inspect", "offline", "full"):
            for online in ("0", "1"):
                with self.subTest(profile=profile, online=online), self.server(profile, online) as (peer, root):
                    tools = self.tools(peer)
                    names = set(tools)
                    if profile == "inspect":
                        self.assertEqual(names, READ_TOOLS | SESSION_TOOLS)
                    elif profile == "offline":
                        self.assertEqual(names, OFFLINE_TOOLS)
                    else:
                        self.assertTrue(OFFLINE_TOOLS <= names)
                    expected_online = profile == "full" and online == "1"
                    self.assertEqual(names & ONLINE_TOOLS, ONLINE_TOOLS if expected_online else set())
                    for name, tool in tools.items():
                        self.assertEqual(tool["inputSchema"]["type"], "object")
                        annotations = tool["annotations"]
                        self.assertEqual(annotations["readOnlyHint"], name in READ_TOOLS, name)
                        self.assertEqual(annotations["destructiveHint"], name not in READ_TOOLS, name)
                        self.assertEqual(annotations["idempotentHint"], name in READ_TOOLS, name)
                        self.assertEqual(annotations["openWorldHint"], name in ONLINE_TOOLS, name)
                    result = peer.request("tools/call", {"name": "get_capabilities", "arguments": {}})
                    self.assertFalse(result.get("isError", False), self.content_text(result))
                    capabilities = result.get("structuredContent") or json.loads(self.content_text(result))
                    self.assertEqual(capabilities["profile"], profile)
                    self.assertEqual(capabilities["online_enabled"], expected_online)
                    self.assertEqual(capabilities["read_roots"], [str(root.resolve())])
                    self.assertEqual(capabilities["write_roots"], [str(root.resolve())])
                    self.assertEqual(capabilities["transport"], "stdio")
                    self.assertEqual(capabilities["physical_equipment_validation"], "not performed")

    def test_offline_invocations_cannot_reach_hidden_equipment_tools(self):
        with self.server() as (peer, root):
            for name in ("start_simulator", "stop_simulator", "plc_connect", "plc_transfer", "write_tags"):
                with self.subTest(tool=name):
                    result = peer.request("tools/call", {"name": name, "arguments": {}})
                    self.assertTrue(result["isError"])
                    self.assertNotIn("attempted vendor", self.content_text(result))

    def test_path_rejection_and_inspect_save_rejection_over_stdio(self):
        with self.server("inspect") as (peer, root):
            result = peer.request("tools/call", {
                "name": "inspect_parameter_csv",
                "arguments": {"path": str(root.parent / "outside.csv")},
            })
            self.assertTrue(result["isError"])
            self.assertIn("READ_ROOTS", self.content_text(result))
            close = peer.request("tools/call", {"name": "close_project", "arguments": {"save": True}})
            self.assertTrue(close["isError"])
            self.assertNotIn("attempted vendor", self.content_text(close))

    def test_simulator_registry_change_requires_explicit_flag(self):
        with self.server("full", "1") as (peer, root):
            result = peer.request("tools/call", {
                "name": "start_simulator",
                "arguments": {"enforce_security": False, "allow_registry_change": False},
            })
            self.assertTrue(result["isError"])
            self.assertIn("allow_registry_change", self.content_text(result))
            self.assertNotIn("attempted vendor", self.content_text(result))

    def test_ping_remains_responsive_and_tool_calls_do_not_interleave(self):
        with self.server("full") as (peer, root):
            first = peer.send_request("tools/call", {
                "name": "protocol_slow_probe", "arguments": {"label": "first", "delay": 0.6},
            })
            marker = root / "probe-started.txt"
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(marker.exists(), "The slow tool did not start")
            second = peer.send_request("tools/call", {
                "name": "protocol_slow_probe", "arguments": {"label": "second", "delay": 0.03},
            })
            ping = peer.send_request("ping")
            self.assertEqual(peer.receive(ping, timeout=0.35), {})
            for request_id in (first, second):
                result = peer.receive(request_id)
                self.assertFalse(result.get("isError", False), self.content_text(result))
            order = result.get("structuredContent") or json.loads(self.content_text(result))
            self.assertEqual(order["order"], ["first:start", "first:end", "second:start", "second:end"])


if __name__ == "__main__":
    unittest.main()
