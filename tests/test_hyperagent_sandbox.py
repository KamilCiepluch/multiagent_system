"""
Unit testy hyperagent/sandbox/runner.py — mockujemy `subprocess.run`, więc nie
trzeba mieć działającego silnika Dockera (mirror konwencji z
test_hyperagent_gateway.py: testujemy WŁASNY kod orkiestrujący, nie Dockera).

Sprawdzamy te właściwości runnera, które realizują izolację z planu:
- kontener jest zawsze odpalany z `--network <internal>`, bez `--privileged`,
  z `--cap-drop ALL` i twardymi limitami zasobów
- `/workspace` trafia do kontenera jako bind-mount (read-write — agent
  edytuje tu siebie), `GATEWAY_URL` to JEDYNY adres, jaki agent dostaje
- przekroczenie timeoutu kończy się `docker kill` + `docker rm -f` i
  wynikiem `timed_out=True` (a nie wyjątkiem czy cichym wyciekiem procesu)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from hyperagent.sandbox.runner import (
    SandboxLimits,
    SandboxResult,
    run_agent_container,
)

_WORKSPACE = Path("/tmp/hyperagent-workspace-gen-3")
_GATEWAY_URL = "http://gateway:8800"


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr)


class TestRunAgentContainer:
    @patch("hyperagent.sandbox.runner.subprocess.run")
    def test_invokes_docker_run_with_isolation_flags(self, mock_run):
        mock_run.return_value = _completed(returncode=0, stdout="agent finished\n")

        result = run_agent_container(_WORKSPACE, gateway_url=_GATEWAY_URL, container_name="hyperagent-agent-test")

        assert isinstance(result, SandboxResult)
        assert result.ok is True
        assert result.exit_code == 0
        assert result.timed_out is False

        args = mock_run.call_args[0][0]
        assert args[0] == "docker"
        assert "run" in args
        # izolacja sieciowa — JEDYNA trasa to sieć internal
        assert "--network" in args and args[args.index("--network") + 1] == "hyperagent_net"
        # brak eskalacji uprawnień
        assert "--privileged" not in args
        assert "--cap-drop" in args and args[args.index("--cap-drop") + 1] == "ALL"
        assert "--security-opt" in args and "no-new-privileges" in args[args.index("--security-opt") + 1]
        # twarde limity zasobów
        for flag in ("--memory", "--cpus", "--pids-limit"):
            assert flag in args
        # /workspace (rw bind-mount) i jedyny adres do świata zewnętrznego
        mount = args[args.index("-v") + 1]
        assert mount == f"{_WORKSPACE}:/workspace"
        env = args[args.index("-e") + 1]
        assert env == f"GATEWAY_URL={_GATEWAY_URL}"
        # nazwany kontener — żeby dało się go znaleźć/zabić po nazwie
        assert "--name" in args and args[args.index("--name") + 1] == "hyperagent-agent-test"
        assert "--rm" in args

    @patch("hyperagent.sandbox.runner.subprocess.run")
    def test_custom_limits_are_passed_through(self, mock_run):
        mock_run.return_value = _completed(returncode=0)
        limits = SandboxLimits(memory="2g", cpus="0.5", pids_limit=64, timeout_seconds=60)

        run_agent_container(_WORKSPACE, gateway_url=_GATEWAY_URL, limits=limits, container_name="c1")

        args = mock_run.call_args[0][0]
        assert args[args.index("--memory") + 1] == "2g"
        assert args[args.index("--cpus") + 1] == "0.5"
        assert args[args.index("--pids-limit") + 1] == "64"
        assert mock_run.call_args.kwargs["timeout"] == 60

    @patch("hyperagent.sandbox.runner.subprocess.run")
    def test_nonzero_exit_is_reported_not_raised(self, mock_run):
        mock_run.return_value = _completed(returncode=1, stdout="", stderr="agent crashed")

        result = run_agent_container(_WORKSPACE, gateway_url=_GATEWAY_URL, container_name="c2")

        assert result.ok is False
        assert result.exit_code == 1
        assert result.timed_out is False
        assert "agent crashed" in result.stderr


class TestTimeoutHandling:
    @patch("hyperagent.sandbox.runner.subprocess.run")
    def test_timeout_force_stops_container_and_reports_timed_out(self, mock_run):
        """Zawieszony/zapętlony agent NIE MOŻE pozostawić działającego
        kontenera — runner musi go brutalnie zabić i posprzątać, niezależnie
        od tego, co kod wewnątrz robi."""
        name = "hyperagent-agent-hung"
        calls: list[list[str]] = []

        def _side_effect(cmd, **kwargs):
            calls.append(cmd)
            if cmd[1] == "run":
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=5, output=b"partial output", stderr=b"")
            return _completed(returncode=0)

        mock_run.side_effect = _side_effect

        result = run_agent_container(
            _WORKSPACE, gateway_url=_GATEWAY_URL, limits=SandboxLimits(timeout_seconds=5), container_name=name
        )

        assert result.timed_out is True
        assert result.exit_code is None
        assert result.container_name == name
        assert "partial output" in result.stdout

        # docker kill <name> i docker rm -f <name> — w tej kolejności, po timeoucie
        kill_calls = [c for c in calls if c[1] == "kill"]
        rm_calls = [c for c in calls if c[1] == "rm"]
        assert kill_calls == [["docker", "kill", name]]
        assert rm_calls == [["docker", "rm", "-f", name]]
        assert calls.index(kill_calls[0]) < calls.index(rm_calls[0])

    @patch("hyperagent.sandbox.runner.subprocess.run")
    def test_run_passes_explicit_timeout_to_subprocess(self, mock_run):
        mock_run.return_value = _completed(returncode=0)

        run_agent_container(_WORKSPACE, gateway_url=_GATEWAY_URL, limits=SandboxLimits(timeout_seconds=42), container_name="c3")

        assert mock_run.call_args.kwargs["timeout"] == 42
