"""The sandbox: run untrusted code in a throwaway Docker container.

Trust model — read this before touching it:

* The **executor** (this process) talks to the Docker daemon, which is
  root-equivalent on the host. The executor is therefore *trusted* and its API
  must be authenticated / loopback-bound. This is the unavoidable Docker-socket
  caveat, not a bug.
* The **executed code** is *untrusted*. It runs in a sibling container with, by
  default: no network, a read-only root filesystem, a non-root user, all Linux
  capabilities dropped, ``no-new-privileges``, a pids cap, memory and CPU caps,
  and a wall-clock timeout. Its only writable storage is tmpfs that dies with
  the container.

The caller names a *language*, never an image — images come only from the
server-side allowlist in :mod:`casanovacode.config`. That is what stops a
caller asking the daemon to run something arbitrary.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass

from .config import ExecConfig, LanguageSpec

log = logging.getLogger(__name__)


class RunnerError(RuntimeError):
    """Raised for bad requests and sandbox setup failures (not code errors).

    A non-zero exit from the *user's* code is a normal result, not a
    RunnerError — it comes back in ``RunResult.exit_code``.
    """


@dataclass(frozen=True)
class RunResult:
    """JSON-ready result of one execution."""

    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    oom_killed: bool
    duration: float
    truncated: bool
    language: str
    image: str

    def as_dict(self) -> dict:
        return asdict(self)


# A tiny POSIX-sh bootstrap: write the submitted code (delivered in the CC_CODE
# env var) into the writable tmpfs workspace, then exec the real interpreter.
#
# Why env + bootstrap instead of docker put_archive: with a read-only root
# filesystem, put_archive is rejected ("container rootfs is marked read-only")
# because the tmpfs /workspace mount does not exist until the container starts.
# Writing the file from inside, after start, targets the mounted tmpfs — so the
# read-only root guarantee stays intact. ``printf %s "$CC_CODE"`` prints the
# value literally (no shell/backslash interpretation), and the real command is
# passed as positional args and reached with exec "$@", so nothing from the
# code or filename is ever re-parsed by the shell.
#
# When stdin is supplied it is delivered the same way (CC_STDIN env -> tmpfs
# file) and redirected into the program, rather than streamed over a docker
# attach socket — one less fragile moving part, and no ordering race.
_BOOTSTRAP = 'printf %s "$CC_CODE" > /workspace/{filename}; exec "$@"'
_BOOTSTRAP_STDIN = (
    'printf %s "$CC_CODE" > /workspace/{filename}; '
    'printf %s "$CC_STDIN" > /workspace/.ccstdin; '
    'exec "$@" < /workspace/.ccstdin'
)


def _truncate(raw: bytes, limit: int) -> tuple[str, bool]:
    if len(raw) > limit:
        return raw[:limit].decode("utf-8", "replace"), True
    return raw.decode("utf-8", "replace"), False


class DockerRunner:
    """Runs code in locked-down, single-use containers via the Docker SDK."""

    def __init__(self, config: ExecConfig, client=None) -> None:
        self.config = config
        self._client = client  # injected in tests; otherwise created lazily

    # -- client / health ------------------------------------------------------

    @property
    def client(self):
        if self._client is None:
            try:
                import docker
            except ImportError as exc:  # pragma: no cover
                raise RunnerError(
                    "docker SDK is not installed. pip install 'casanovacode' or "
                    "pip install docker"
                ) from exc
            try:
                self._client = docker.from_env()
            except Exception as exc:  # noqa: BLE001 — daemon unreachable
                raise RunnerError(
                    f"cannot reach the Docker daemon: {exc}. Is Docker running, "
                    "and is the socket available to this process?"
                ) from exc
        return self._client

    def languages(self) -> list[str]:
        return sorted(self.config.languages)

    def info(self) -> dict:
        try:
            version = self.client.version()
            reachable = True
            server = version.get("Version")
        except Exception as exc:  # noqa: BLE001
            reachable = False
            server = f"unreachable: {exc}"
        return {
            "docker_reachable": reachable,
            "docker_version": server,
            "languages": self.languages(),
            "network": "enabled" if self.config.allow_network else "disabled",
        }

    # -- image allowlist ------------------------------------------------------

    def _ensure_image(self, image: str) -> None:
        from docker.errors import ImageNotFound

        try:
            self.client.images.get(image)
            return
        except ImageNotFound:
            pass
        except Exception as exc:  # noqa: BLE001
            raise RunnerError(f"could not query image {image}: {exc}") from exc

        if not self.config.auto_pull:
            raise RunnerError(
                f"image {image} is not present and CCODE_AUTO_PULL is off. "
                f"Pull it on the host: docker pull {image}"
            )
        try:
            log.info("pulling allowlisted image %s", image)
            self.client.images.pull(image)
        except Exception as exc:  # noqa: BLE001
            raise RunnerError(f"could not pull image {image}: {exc}") from exc

    # -- the run --------------------------------------------------------------

    def _create_kwargs(self, spec: LanguageSpec, code: str, stdin: str | None) -> dict:
        cfg = self.config
        template = _BOOTSTRAP_STDIN if stdin is not None else _BOOTSTRAP
        bootstrap = template.format(filename=spec.filename)
        # sh -c <bootstrap> <argv0> <real cmd...>  → the real cmd is "$@".
        command = ["/bin/sh", "-c", bootstrap, "casanovacode", *spec.cmd]
        environment = {"HOME": "/workspace", "TMPDIR": "/tmp", "CC_CODE": code}
        if stdin is not None:
            environment["CC_STDIN"] = stdin
        kwargs: dict = {
            "image": spec.image,
            "command": command,
            "working_dir": "/workspace",
            "user": cfg.user,
            "detach": True,
            "read_only": True,  # read-only root fs
            "mem_limit": cfg.memory,
            "memswap_limit": cfg.memory,  # == mem_limit disables swap
            "nano_cpus": int(cfg.cpus * 1_000_000_000),
            "pids_limit": cfg.pids_limit,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "environment": environment,
            "tmpfs": {
                "/workspace": f"rw,size={cfg.workspace_size},mode=1777",
                "/tmp": f"rw,size={cfg.tmp_size},mode=1777",
            },
            "labels": {"casanovacode": "1"},
        }
        if cfg.allow_network:
            kwargs["network_mode"] = cfg.network
        else:
            kwargs["network_disabled"] = True
        return kwargs

    def run(
        self,
        *,
        language: str,
        code: str,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> RunResult:
        spec = self.config.languages.get(language)
        if spec is None:
            allowed = ", ".join(self.languages()) or "(none configured)"
            raise RunnerError(
                f"language '{language}' is not allowed. Allowed: {allowed}"
            )
        if not code or not code.strip():
            raise RunnerError("code is empty")

        wall = self.config.clamp_timeout(timeout)
        self._ensure_image(spec.image)

        kwargs = self._create_kwargs(spec, code, stdin)

        container = None
        started = time.monotonic()
        try:
            container = self.client.containers.create(**kwargs)
            container.start()

            timed_out = False
            exit_code: int | None = None
            try:
                result = container.wait(timeout=wall)
                exit_code = int(result.get("StatusCode", -1))
            except Exception as exc:  # noqa: BLE001 — timeout surfaces here
                if _is_timeout(exc):
                    timed_out = True
                    _safe_kill(container)
                else:
                    raise RunnerError(f"waiting on container failed: {exc}") from exc

            duration = time.monotonic() - started
            stdout, t_out = _truncate(
                container.logs(stdout=True, stderr=False), self.config.max_output_bytes
            )
            stderr, t_err = _truncate(
                container.logs(stdout=False, stderr=True), self.config.max_output_bytes
            )
            oom = _oom_killed(container)

            return RunResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=None if timed_out else exit_code,
                timed_out=timed_out,
                oom_killed=oom,
                duration=round(duration, 3),
                truncated=t_out or t_err,
                language=language,
                image=spec.image,
            )
        finally:
            if container is not None and self.config.remove:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    log.warning("failed to remove container %s", getattr(container, "id", "?"))

def _is_timeout(exc: Exception) -> bool:
    # container.wait(timeout=...) surfaces its timeout in different shapes across
    # docker-py / urllib3 versions: requests ReadTimeout, or a ConnectionError
    # wrapping urllib3's ReadTimeoutError. Walk the whole cause/context chain
    # and match either a Timeout-ish type name or a "timed out" message, so we
    # classify it as a timeout (kill + flag) rather than a hard error.
    seen = []
    cur: BaseException | None = exc
    for _ in range(8):
        if cur is None:
            break
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    for e in seen:
        if "Timeout" in type(e).__name__:
            return True
        if "timed out" in str(e).lower():
            return True
    return False


def _safe_kill(container) -> None:
    try:
        container.kill()
    except Exception:  # noqa: BLE001 — it may have already exited
        pass


def _oom_killed(container) -> bool:
    try:
        container.reload()
        return bool(container.attrs.get("State", {}).get("OOMKilled", False))
    except Exception:  # noqa: BLE001
        return False


def build_runner(config: ExecConfig | None = None, client=None) -> DockerRunner:
    return DockerRunner(config or ExecConfig.from_env(), client=client)


__all__ = ["DockerRunner", "RunResult", "RunnerError", "build_runner"]
