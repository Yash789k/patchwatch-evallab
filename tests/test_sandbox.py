"""Adversarial boundary checks against the real Docker runtime."""

import pytest

from patchwatch.sandbox import DockerSandbox

pytestmark = pytest.mark.docker


@pytest.fixture
def sandbox():
    runtime = DockerSandbox()
    runtime.available()
    runtime.deps = runtime._volume()
    try:
        yield runtime
    finally:
        runtime.close()


def test_container_cannot_reach_network_host_secrets_or_modify_source(
    sandbox, tmp_path, monkeypatch
):
    monkeypatch.setenv("PATCHWATCH_HOST_SECRET", "never-forward-this")
    (tmp_path / "test_boundary.py").write_text("""import os
import socket
from pathlib import Path


def test_boundary():
    assert os.geteuid() == 65534
    assert "PATCHWATCH_HOST_SECRET" not in os.environ
    assert not Path("/var/run/docker.sock").exists()
    try:
        assert not Path("/root/.ssh").exists()
    except PermissionError:
        pass
    status = Path("/proc/self/status").read_text()
    assert "CapEff:\\t0000000000000000" in status
    assert "NoNewPrivs:\\t1" in status
    try:
        Path("/input/tampered.py").write_text("bad")
    except OSError:
        pass
    else:
        raise AssertionError("Source mount was writable")
    sock = socket.socket()
    sock.settimeout(0.2)
    try:
        sock.connect(("1.1.1.1", 443))
    except OSError:
        pass
    else:
        raise AssertionError("Network was reachable")
    finally:
        sock.close()
    Path("local-only.txt").write_text("disposable")
""")
    tmp_path.chmod(0o755)
    result = sandbox.check(tmp_path, "test", "boundary")
    assert result.passed, result.log
    assert result.tests_passed == 1
    assert not (tmp_path / "tampered.py").exists()
    assert not (tmp_path / "local-only.txt").exists()


def test_all_skipped_tests_are_not_verification(sandbox, tmp_path):
    (tmp_path / "test_skipped.py").write_text(
        'import pytest\n\n@pytest.mark.skip(reason="not proof")\ndef test_skipped():\n    assert True\n'
    )
    tmp_path.chmod(0o755)
    result = sandbox.check(tmp_path, "test", "skipped")
    assert not result.passed
    assert result.tests_passed == 0
    assert result.tests_skipped == 1


def test_timeout_stops_container(sandbox, tmp_path):
    (tmp_path / "test_hang.py").write_text("import time\n\ndef test_hang():\n    time.sleep(60)\n")
    sandbox.timeout = 5
    tmp_path.chmod(0o755)
    result = sandbox.check(tmp_path, "test", "timeout")
    assert not result.passed
    assert result.exit_code == 124
