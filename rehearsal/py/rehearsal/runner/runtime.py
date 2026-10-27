"""Docker execution boundary for one world instance.

Layout per instance ``rh-<id>``:

* ``rh-<id>-int``  internal network (no egress). Application services and the
  providers container live here; services resolve each other by name.
* ``rh-<id>-ext``  ordinary bridge for the providers container, which
  publishes its port on 127.0.0.1 and acts as the authenticated edge proxy.
  Containerized workers join this bridge to reach the proxy without host loopback.
* one named volume per service data path, plus every VOLUME the image declares
  (otherwise Docker would create anonymous volumes that reset cannot see).

Reset removes the containers, restores every volume from a snapshot, and
recreates the containers, so state left in a container's writable layer cannot
leak between episodes.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets as pysecrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..core.contracts import ServiceSpec, WorldManifest, image_ref, render_template

PROVIDERS_DIR = Path(__file__).resolve().parent.parent / "providers"
PROVIDER_PORT = 9000
SMTP_PORT = 2525
DROP_CAPS = ["NET_RAW", "MKNOD", "AUDIT_WRITE", "SETFCAP", "SYS_CHROOT"]


class RuntimeError_(Exception):
    """Raised for execution-boundary failures; message is safe to show to builders."""


def _run(args: list[str], *, timeout: float = 600, check: bool = True, input_: str | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input_)
    if check and proc.returncode != 0:
        raise RuntimeError_(f"{' '.join(args[:4])}... failed ({proc.returncode}): {(proc.stderr or proc.stdout)[-2000:]}")
    return proc


def providers_image() -> str:
    digest = hashlib.sha256()
    for name in ("app.py", "Dockerfile"):
        digest.update((PROVIDERS_DIR / name).read_bytes())
    tag = f"rehearsal-providers:{digest.hexdigest()[:12]}"
    if _run(["docker", "image", "inspect", tag], check=False).returncode != 0:
        with tempfile.TemporaryDirectory() as ctx:
            for name in ("app.py", "Dockerfile"):
                shutil.copy(PROVIDERS_DIR / name, Path(ctx) / name)
            _run(["docker", "build", "-q", "-t", tag, ctx], timeout=900)
    return tag


def build_service_image(service: ServiceSpec, source_dir: Path, world_key: str) -> tuple[str, str]:
    """Builds a ``build`` service; returns (tag, build log tail)."""
    assert service.build is not None
    context = (source_dir / service.build.context).resolve()
    if not context.is_relative_to(source_dir.resolve()):
        raise RuntimeError_("build context escapes the source tree")
    tag = f"rh-img-{world_key}-{service.name}"
    args = ["docker", "build", "-t", tag]
    with tempfile.TemporaryDirectory() as tmp:
        if service.build.dockerfile_inline:
            df = Path(tmp) / "Dockerfile"
            df.write_text(service.build.dockerfile_inline)
            args += ["-f", str(df)]
        else:
            dockerfile = (context / (service.build.dockerfile or "Dockerfile")).resolve()
            if not dockerfile.is_relative_to(context):
                raise RuntimeError_("Dockerfile escapes the build context")
            args += ["-f", str(dockerfile)]
        try:
            proc = _run([*args, str(context)], timeout=3600, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError_(f"image build for {service.name} did not finish within an hour") from exc
    log = (proc.stdout + proc.stderr)[-6000:]
    if proc.returncode != 0:
        raise RuntimeError_(f"image build for {service.name} failed:\n{log}")
    return tag, log


def image_volumes(image: str) -> list[str]:
    image = image_ref(image)
    proc = _run(["docker", "image", "inspect", "--format", "{{json .Config.Volumes}}", "--", image], check=False)
    if proc.returncode != 0:
        _run(["docker", "pull", "-q", "--", image], timeout=1800)
        proc = _run(["docker", "image", "inspect", "--format", "{{json .Config.Volumes}}", "--", image])
    vols = json.loads(proc.stdout.strip() or "null") or {}
    return sorted(vols)


def inspect_image(image: str) -> dict[str, Any]:
    """Default command, entrypoint, env, ports, volumes, user, and workdir of an image."""
    image_volumes(image)  # pulls when missing
    cfg = json.loads(_run(["docker", "image", "inspect", "--format", "{{json .Config}}", "--", image]).stdout)
    return {k: cfg.get(k) for k in ("Cmd", "Entrypoint", "Env", "ExposedPorts", "Volumes", "User", "WorkingDir", "Healthcheck")}


def topo_order(services: list[ServiceSpec]) -> list[ServiceSpec]:
    by_name = {s.name: s for s in services}
    order: list[ServiceSpec] = []
    state: dict[str, int] = {}

    def visit(name: str) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            raise RuntimeError_(f"dependency cycle at {name}")
        state[name] = 1
        for dep in by_name[name].depends_on:
            visit(dep)
        state[name] = 2
        order.append(by_name[name])

    for s in services:
        visit(s.name)
    return order


@dataclass
class InstanceRecord:
    """Everything needed to reattach to a running instance after a worker restart."""

    instance_id: str
    manifest: dict[str, Any]
    secrets: dict[str, str]
    admin_token: str
    images: dict[str, str] = field(default_factory=dict)  # service -> resolved image
    volumes: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # service -> [(volume, path)]

    def to_json(self) -> dict[str, Any]:
        return self.__dict__ | {"volumes": {k: [list(v) for v in vs] for k, vs in self.volumes.items()}}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "InstanceRecord":
        data = dict(data)
        data["volumes"] = {k: [tuple(v) for v in vs] for k, vs in data.get("volumes", {}).items()}
        return cls(**data)


def hostnames(service: str) -> list[str]:
    """Names a service answers to inside the world: as written, hyphenated, and a fully qualified
    form for frameworks whose URL validators require a top-level domain (Django's URLValidator)."""
    dash = service.replace("_", "-")
    return list(dict.fromkeys([service, dash, f"{dash}.world.test"]))


class WorldInstance:
    def __init__(self, record: InstanceRecord):
        self.record = record
        self.manifest = WorldManifest.model_validate(record.manifest)
        self.prefix = f"rh-{record.instance_id}"
        self._edge: str | None = None
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------ factory

    @classmethod
    def create(
        cls,
        manifest: WorldManifest,
        *,
        secrets: dict[str, str],
        source_dir: Path | None = None,
        world_key: str = "dev",
        log: Any = None,
        snapshot: Path | None = None,
    ) -> "WorldInstance":
        """Builds/pulls images and provisions networks, volumes, and containers.

        With ``snapshot``, volumes are restored before first start and one-shot
        services are skipped: their effects are already in the snapshot."""
        instance_id = pysecrets.token_hex(4)
        images: dict[str, str] = {}
        for svc in manifest.services:
            if svc.build is not None:
                if source_dir is None:
                    raise RuntimeError_(f"service {svc.name} needs a source checkout to build")
                if log:
                    log(f"building image for {svc.name}")
                images[svc.name], _ = build_service_image(svc, source_dir, world_key)
            else:
                images[svc.name] = svc.image  # type: ignore[assignment]
        record = InstanceRecord(instance_id, manifest.model_dump(mode="json", by_alias=True), secrets, pysecrets.token_urlsafe(24), images)
        inst = cls(record)
        for svc in manifest.services:
            if svc.volumes_from:
                continue  # shares the target service's volumes
            paths = sorted(set(svc.data_paths) | set(image_volumes(images[svc.name])))
            record.volumes[svc.name] = [(f"{inst.prefix}-{svc.name}-{i}", p) for i, p in enumerate(paths)]
        record.volumes["providers"] = [(f"{inst.prefix}-providers-0", "/data")]
        try:
            inst._provision(log, snapshot=snapshot)
        except BaseException as exc:
            detail = inst.collect_logs()
            inst.destroy()
            if isinstance(exc, RuntimeError_):
                raise RuntimeError_(f"{exc}\n\n--- service logs ---\n{detail}") from exc
            raise
        return inst

    def _scopes(self) -> dict[str, dict[str, Any]]:
        return {
            "secret": self.record.secrets,
            "service": {s.name: s.name for s in self.manifest.services},
            "provider": {
                "http": f"http://providers:{PROVIDER_PORT}",
                "host": "providers",
                "smtp_port": SMTP_PORT,
                "sink": f"http://providers:{PROVIDER_PORT}/sink",
            },
        }

    def _provision(self, log: Any = None, snapshot: Path | None = None) -> None:
        _run(["docker", "network", "create", "--internal", "--label", "rehearsal=1", f"{self.prefix}-int"])
        _run(["docker", "network", "create", "--label", "rehearsal=1", f"{self.prefix}-ext"])
        fresh = []
        for vols in self.record.volumes.values():
            for vol, _ in vols:
                _run(["docker", "volume", "create", "--label", "rehearsal=1", vol])
                fresh.append(vol)
        if snapshot is not None:
            self._load_volumes(snapshot)
        elif fresh:
            # Images that run as a non-root user cannot write a data path the image does not ship (the volume
            # root is created root-owned). Paths the image does ship get its ownership when Docker first mounts them.
            mounts = [x for i, vol in enumerate(fresh) for x in ("-v", f"{vol}:/v/{i}")]
            _run(["docker", "run", "--rm", "--network", "none", *mounts, "--entrypoint", "sh", providers_image(), "-c", "chmod 0777 /v/*"], check=False)
        self._start_providers()
        self._start_services(run_oneshots=snapshot is None, log=log)

    def collect_logs(self, tail: int = 60) -> str:
        parts = []
        for svc in self.manifest.services:
            text = self.logs(svc.name, tail)
            if text.strip() and "No such container" not in text:
                parts.append(f"[{svc.name}]\n{text[-3000:]}")
        return "\n".join(parts)[-12000:]

    # ------------------------------------------------------------------ containers

    def _hardening(self) -> list[str]:
        s = settings()
        args = ["--memory", s.container_memory, "--cpus", s.container_cpus, "--pids-limit", str(s.container_pids)]
        args += ["--security-opt", "no-new-privileges", "--label", "rehearsal=1"]
        for cap in DROP_CAPS:
            args += ["--cap-drop", cap]
        return args

    def _start_providers(self) -> None:
        # the proxy sends Host: <hyphenated name>; underscores are not valid in hostnames and frameworks reject them
        services = {s.name: f"http://{hostnames(s.name)[1]}:{s.port}" for s in self.manifest.services if s.port}
        name = f"{self.prefix}-providers"
        args = ["docker", "run", "-d", "--name", name, "--network", f"{self.prefix}-ext", "-p", f"127.0.0.1::{PROVIDER_PORT}"]
        args += self._hardening()
        args += ["-v", f"{self.prefix}-providers-0:/data", "-e", f"RH_ADMIN_TOKEN={self.record.admin_token}", "-e", f"RH_SERVICES={json.dumps(services)}"]
        _run([*args, providers_image()])
        _run(["docker", "network", "connect", "--alias", "providers", f"{self.prefix}-int", name])
        self._edge = None
        self._wait(lambda: self.edge_client().get("/__health").status_code == 200, 60, "providers")

    def _service_args(self, svc: ServiceSpec) -> list[str]:
        scopes = self._scopes()
        args = ["--name", f"{self.prefix}-{svc.name}", "--network", f"{self.prefix}-int"]
        for alias in hostnames(svc.name):
            args += ["--network-alias", alias]
        args += self._hardening()
        for vol, path in self.record.volumes[svc.volumes_from or svc.name]:
            args += ["-v", f"{vol}:{path}"]
        for k, v in svc.env.items():
            args += ["-e", f"{k}={render_template(v, scopes)}"]
        if svc.user:
            args.append(f"--user={svc.user}")
        if svc.entrypoint is not None:
            args.append(f"--entrypoint={svc.entrypoint[0] if svc.entrypoint else ''}")
        # "--" ends the options: whatever the image string holds, docker reads it as the image
        args += ["--", image_ref(self.record.images[svc.name])]
        if svc.entrypoint and len(svc.entrypoint) > 1:
            args += svc.entrypoint[1:]
        if svc.command:
            args += [render_template(c, scopes) for c in svc.command]
        return args

    def _start_services(self, *, run_oneshots: bool, log: Any = None) -> None:
        for svc in topo_order(self.manifest.services):
            if svc.oneshot:
                if not run_oneshots:
                    continue
                if log:
                    log(f"running one-shot {svc.name}")
                try:
                    proc = _run(["docker", "run", *self._service_args(svc)], timeout=svc.health.timeout_s, check=False)
                except subprocess.TimeoutExpired as exc:  # a slow setup step is a fact for the builder, not a crash of the build
                    so_far = self.logs(svc.name, 60)
                    _run(["docker", "rm", "-f", f"{self.prefix}-{svc.name}"], check=False)
                    raise RuntimeError_(f"one-shot {svc.name} did not finish within {svc.health.timeout_s} s (its health.timeout_s). "
                                        f"Raise health.timeout_s for a slow setup step such as migrations, or make the step do less. "
                                        f"Output so far:\n{so_far[-3000:]}") from exc
                out = (proc.stdout + proc.stderr)[-3000:]
                if proc.returncode != 0:
                    hint = "" if svc.volumes_from else (
                        "\nNote: this one-shot has its own empty volumes. To work on another service's files or database files, set "
                        "volumes_from to that service; to run after a service has started and created its files, list it in depends_on."
                    )
                    death = self._death(svc.name, proc.returncode)
                    _run(["docker", "rm", "-f", f"{self.prefix}-{svc.name}"], check=False)
                    raise RuntimeError_(f"one-shot {svc.name} exited {proc.returncode}{death}:\n{out}{hint}")
                _run(["docker", "rm", "-f", f"{self.prefix}-{svc.name}"], check=False)
                continue
            if log:
                log(f"starting {svc.name}")
            _run(["docker", "run", "-d", *self._service_args(svc)])
            self.wait_healthy(svc)

    def _death(self, service: str, code: int | None = None) -> str:
        """Why a container died, when Docker knows: the logs alone do not show an out-of-memory kill."""
        out = _run(["docker", "inspect", "-f", "{{.State.OOMKilled}} {{.State.ExitCode}}", f"{self.prefix}-{service}"], check=False).stdout.split()
        oom = out[:1] == ["true"] or (code if code is not None else int(out[1]) if len(out) > 1 and out[1].lstrip("-").isdigit() else 0) == 137
        if not oom:
            return f" (exit code {out[1]})" if code is None and len(out) > 1 else ""
        limit = settings().container_memory
        return (
            f" (killed for exceeding its {limit} memory limit; the container reports the host's CPU count, so servers and workers "
            "that start one process per CPU must be given an explicit small worker/concurrency count)"
        )

    def wait_healthy(self, svc: ServiceSpec) -> None:
        h = svc.health

        def probe() -> bool:
            state = _run(["docker", "inspect", "-f", "{{.State.Status}}", f"{self.prefix}-{svc.name}"], check=False).stdout.strip()
            if state in ("exited", "dead"):
                raise RuntimeError_(f"service {svc.name} exited during startup{self._death(svc.name)}:\n{self.logs(svc.name, 80)}")
            if h.command:  # templates as in env and command: a check such as pg_isready -U {{secret.DB_USER}} needs the real value
                scopes = self._scopes()
                return self.exec(svc.name, [render_template(c, scopes) for c in h.command], timeout=30)[0] == 0
            if h.http_path and svc.port:
                try:
                    return self.http(svc.name, "GET", h.http_path, timeout=10).status_code < 500
                except httpx.HTTPError:
                    return False
            return state == "running"

        self._wait(probe, h.timeout_s, svc.name)

    def _wait(self, probe: Any, timeout_s: float, what: str) -> None:
        deadline = time.monotonic() + timeout_s
        delay = 0.5
        while time.monotonic() < deadline:
            try:
                if probe():
                    return
            except RuntimeError_:
                raise
            except Exception:  # noqa: BLE001 - startup probes fail in many ways
                pass
            time.sleep(delay)
            delay = min(delay * 1.5, 5)
        raise RuntimeError_(f"{what} not healthy after {timeout_s}s:\n{self.logs(what, 60) if what != 'providers' else ''}")

    # ------------------------------------------------------------------ access

    def edge_url(self) -> str:
        if self._edge is None:
            worker = os.environ.get("REHEARSAL_WORKER_CONTAINER")
            if worker:
                network = f"{self.prefix}-ext"
                networks = json.loads(_run(["docker", "inspect", "-f", "{{json .NetworkSettings.Networks}}", worker]).stdout)
                if network not in networks:
                    _run(["docker", "network", "connect", network, worker])
                self._edge = f"http://{self.prefix}-providers:{PROVIDER_PORT}"
            else:
                out = _run(["docker", "port", f"{self.prefix}-providers", str(PROVIDER_PORT)]).stdout.splitlines()[0]
                self._edge = f"http://127.0.0.1:{out.rsplit(':', 1)[1]}"
            self._client = None
        return self._edge

    def edge_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.edge_url(), headers={"X-Rehearsal-Admin": self.record.admin_token}, timeout=60.0,
                trust_env=False,  # Keep admin credentials off environment-configured HTTP proxies.
            )
        return self._client

    def http(
        self,
        service: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> httpx.Response:
        if not path.startswith("/"):
            path = "/" + path
        return self.edge_client().request(
            method, f"/__svc/{service}{path}", headers=headers or {}, json=json_body, params=params, timeout=timeout
        )

    def journal(self) -> list[dict[str, Any]]:
        resp = self.edge_client().get("/__admin/journal")
        resp.raise_for_status()
        return resp.json()

    def exec(
        self, service: str, command: list[str], *, user: str | None = None, timeout: float = 300, stdin: str | None = None
    ) -> tuple[int, str, str]:
        args = ["docker", "exec"] + (["-i"] if stdin is not None else [])
        if user:
            args += ["-u", user]
        try:
            proc = _run([*args, f"{self.prefix}-{service}", *command], timeout=timeout, check=False, input_=stdin)
        except subprocess.TimeoutExpired:
            return 124, "", f"timed out after {timeout}s"
        return proc.returncode, proc.stdout, proc.stderr

    def copy_out(self, service: str, path: str, dest: Path) -> bool:
        return _run(["docker", "cp", f"{self.prefix}-{service}:{path}", str(dest)], check=False).returncode == 0

    def logs(self, service: str, tail: int = 100) -> str:
        proc = _run(["docker", "logs", "--tail", str(tail), f"{self.prefix}-{service}"], check=False)
        return (proc.stdout + proc.stderr)[-8000:]

    # ------------------------------------------------------------------ reset

    def _all_volumes(self) -> list[str]:
        return [vol for vols in self.record.volumes.values() for vol, _ in vols]

    def _logical(self) -> list[tuple[str, str, str]]:
        """(volume, snapshot key, container path); keys are stable across instances."""
        return [(vol, f"{svc}-{i}", path) for svc, vols in sorted(self.record.volumes.items()) for i, (vol, path) in enumerate(vols)]

    def _remove_containers(self) -> None:
        names = [f"{self.prefix}-{s.name}" for s in self.manifest.services] + [f"{self.prefix}-providers"]
        _run(["docker", "rm", "-f", *names], check=False)
        self._edge = None
        self._client = None

    def snapshot(self, directory: Path) -> None:
        """Captures every volume into ``directory`` while containers are stopped."""
        directory.mkdir(parents=True, exist_ok=True)
        names = [f"{self.prefix}-{s.name}" for s in self.manifest.services if not s.oneshot]
        _run(["docker", "stop", "-t", "20", *names, f"{self.prefix}-providers"], check=False, timeout=180)
        mounts: list[str] = []
        script = []
        for i, (vol, key, _) in enumerate(self._logical()):
            mounts += ["-v", f"{vol}:/v{i}:ro"]
            script.append(f"tar -C /v{i} -cpf /out/{key}.tar .")
        _run(["docker", "run", "--rm", *mounts, "-v", f"{directory}:/out", providers_image(), "sh", "-c", " && ".join(script)], timeout=900)
        (directory / "volumes.json").write_text(json.dumps([[k, p] for _, k, p in self._logical()]))
        self._remove_containers()
        self._start_providers()
        self._start_services(run_oneshots=False)

    def _load_volumes(self, directory: Path) -> None:
        expected = [tuple(x) for x in json.loads((directory / "volumes.json").read_text())]
        if expected != [(k, p) for _, k, p in self._logical()]:
            raise RuntimeError_("snapshot volume layout does not match this world's services")
        mounts: list[str] = []
        script = []
        for i, (vol, key, _) in enumerate(self._logical()):
            mounts += ["-v", f"{vol}:/v{i}"]
            script.append(f"find /v{i} -mindepth 1 -delete && tar -C /v{i} -xpf /in/{key}.tar")
        _run(["docker", "run", "--rm", *mounts, "-v", f"{directory}:/in:ro", providers_image(), "sh", "-c", " && ".join(script)], timeout=900)

    def restore(self, directory: Path) -> None:
        """Returns every service to the snapshot state with fresh containers."""
        self._remove_containers()
        self._load_volumes(directory)
        self._start_providers()
        self._start_services(run_oneshots=False)

    def alive(self) -> bool:
        proc = _run(["docker", "inspect", "-f", "{{.State.Running}}", f"{self.prefix}-providers"], check=False)
        return proc.stdout.strip() == "true"

    def destroy(self) -> None:
        self._remove_containers()
        _run(["docker", "volume", "rm", "-f", *self._all_volumes()], check=False)
        network = f"{self.prefix}-ext"
        remaining = _run(["docker", "network", "inspect", "-f", "{{json .Containers}}", network], check=False)
        if remaining.returncode == 0:
            # Reattached instances may have endpoints from several workers; detach all before removal.
            for container in json.loads(remaining.stdout) or {}:
                _run(["docker", "network", "disconnect", "-f", network, container], check=False)
        _run(["docker", "network", "rm", f"{self.prefix}-int", f"{self.prefix}-ext"], check=False)


def new_secrets(names: list[str]) -> dict[str, str]:
    # Hex keeps secrets valid in URLs, DSNs, and shell commands.
    return {n: pysecrets.token_hex(16) for n in names}
