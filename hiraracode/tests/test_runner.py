"""Tests for the Docker sandbox runner, using a fake Docker client."""

from __future__ import annotations

import pytest

from hiraracode.config import ExecConfig
from hiraracode.runner import DockerRunner, RunnerError


def _runner(client, **cfg_overrides) -> DockerRunner:
    return DockerRunner(ExecConfig(**cfg_overrides), client=client)


def test_happy_path_returns_output(make_client):
    client = make_client(stdout=b"hello\n", stderr=b"", exit_code=0)
    runner = _runner(client)
    result = runner.run(language="python", code="print('hello')")
    assert result.stdout == "hello\n"
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.language == "python"
    assert result.image == "python:3.12-slim"
    # code is delivered via the CC_CODE env var (written into tmpfs by the
    # bootstrap after start — see the read-only-root note in runner.py)
    kw = client.containers.created_kwargs
    assert kw["environment"]["CC_CODE"] == "print('hello')"
    assert kw["command"][:2] == ["/bin/sh", "-c"]
    assert kw["command"][-1] == "/workspace/main.py"
    assert client.containers.container.started is True
    assert client.containers.container.removed is True


def test_sandbox_is_locked_down_by_default(make_client):
    client = make_client()
    _runner(client).run(language="python", code="print(1)")
    kw = client.containers.created_kwargs
    assert kw["network_disabled"] is True          # no network
    assert "network_mode" not in kw
    assert kw["read_only"] is True                  # read-only root fs
    assert kw["user"] == "65534:65534"              # non-root
    assert kw["cap_drop"] == ["ALL"]                # no capabilities
    assert "no-new-privileges:true" in kw["security_opt"]
    assert kw["mem_limit"] == kw["memswap_limit"]   # swap disabled
    assert kw["pids_limit"] == 128
    assert "/workspace" in kw["tmpfs"] and "/tmp" in kw["tmpfs"]


def test_network_can_be_enabled(make_client):
    client = make_client()
    _runner(client, allow_network=True).run(language="python", code="print(1)")
    kw = client.containers.created_kwargs
    assert kw.get("network_mode") == "bridge"
    assert "network_disabled" not in kw


def test_nonzero_exit_is_a_result_not_an_error(make_client):
    client = make_client(exit_code=1, stderr=b"boom\n")
    result = _runner(client).run(language="python", code="raise SystemExit(1)")
    assert result.exit_code == 1
    assert result.stderr == "boom\n"


def test_timeout_kills_and_flags(make_client):
    client = make_client(raise_timeout=True)
    result = _runner(client).run(language="python", code="while True: pass", timeout=1)
    assert result.timed_out is True
    assert result.exit_code is None
    assert client.containers.container.killed is True
    assert client.containers.container.removed is True


def test_oom_is_reported(make_client):
    client = make_client(exit_code=137, oom_killed=True)
    result = _runner(client).run(language="python", code="x = ' ' * 10**12")
    assert result.oom_killed is True


def test_output_is_truncated(make_client):
    client = make_client(stdout=b"x" * 500)
    result = _runner(client, max_output_bytes=100).run(language="python", code="print(1)")
    assert len(result.stdout) == 100
    assert result.truncated is True


def test_unknown_language_rejected(make_client):
    with pytest.raises(RunnerError) as exc:
        _runner(make_client()).run(language="haskell", code="main = print 1")
    assert "not allowed" in str(exc.value)


def test_empty_code_rejected(make_client):
    with pytest.raises(RunnerError):
        _runner(make_client()).run(language="python", code="   ")


def test_missing_image_is_pulled_from_allowlist(make_client):
    client = make_client(present_images=())  # nothing present
    _runner(client).run(language="python", code="print(1)")
    assert "python:3.12-slim" in client.images.pulled


def test_missing_image_not_pulled_when_autopull_off(make_client):
    client = make_client(present_images=())
    with pytest.raises(RunnerError) as exc:
        _runner(client, auto_pull=False).run(language="python", code="print(1)")
    assert "CCODE_AUTO_PULL" in str(exc.value)
    assert client.images.pulled == []


def test_stdin_is_fed_to_the_process(make_client):
    client = make_client(stdout=b"got it\n")
    _runner(client).run(language="python", code="import sys; print(sys.stdin.read())", stdin="hi")
    kw = client.containers.created_kwargs
    # stdin is delivered via CC_STDIN env and redirected from a tmpfs file
    assert kw["environment"]["CC_STDIN"] == "hi"
    assert "< /workspace/.ccstdin" in kw["command"][2]  # redirect in bootstrap
    assert kw["command"][-1] == "/workspace/main.py"  # real cmd still runs


def test_timeout_is_clamped_to_ceiling(make_client):
    client = make_client()
    runner = _runner(client, max_timeout=5.0)
    # a caller asking for 999s is capped; we can't see wait() args on the fake,
    # so assert via clamp_timeout directly.
    assert runner.config.clamp_timeout(999) == 5.0
    assert runner.config.clamp_timeout(2) == 2.0
    assert runner.config.clamp_timeout(None) == 5.0
