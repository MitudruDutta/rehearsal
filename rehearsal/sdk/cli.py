"""rehearsal command-line interface."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _client() -> Any:
    from .client import Rehearsal

    return Rehearsal()


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, default=str))


def _watch(stream: Any) -> None:
    for ev in stream:
        actor = f"[{ev['actor_id']}] " if ev.get("actor_id") else ""
        gv = f" (goal v{ev['goal_version']})" if ev.get("goal_version") else ""
        print(f"{ev['created_at'][11:19]} {ev['type']:<28} {actor}{ev['summary']}{gv}", flush=True)


SERVER_MODULES = {"fastapi", "uvicorn", "sqlalchemy", "alembic", "psycopg", "itsdangerous", "openai", "pydantic", "multipart"}


HINTS = {
    401: "Check REHEARSAL_API_KEY: the key is missing, mistyped, or revoked. Create one on the console's API keys page.",
    402: "The workspace's plan does not cover this. See the console's Billing page for what is left and how to get more.",
    403: "This API key's access does not allow that. Use a key with \"Build and evaluate\" or \"Full access\".",
    404: "Check the id: list what exists with 'rehearsal apps list', 'worlds list', 'profiles list' or 'runs show'.",
    409: "Not possible in the current state; the message above says why.",
    422: "Check the arguments.",
    429: "Too many jobs are running in this workspace. Wait for one to finish, or stop one.",
}


def main(argv: list[str] | None = None) -> None:
    import httpx

    from .client import RehearsalError

    try:
        _main(argv)
    except RehearsalError as exc:
        hint = HINTS.get(exc.status) or ("The server had a problem; try again, and check the server log if it persists." if exc.status >= 500 else "")
        sys.exit(f"Error ({exc.status}): {exc.detail}" + (f"\n{hint}" if hint else ""))
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        from .client import DEFAULT_URL, saved_login

        url = os.environ.get("REHEARSAL_URL") or saved_login().get("url") or DEFAULT_URL
        sys.exit(f"Cannot reach Rehearsal at {url} ({exc.__class__.__name__}). Check the URL (`rehearsal login --url ...`) and that the server is running.")
    except httpx.TimeoutException:
        sys.exit("Rehearsal did not answer in time. Try again; long work runs as jobs, so check 'rehearsal jobs show JOB_ID'.")
    except ValueError as exc:
        if "REHEARSAL_API_KEY" not in str(exc):
            raise
        sys.exit("Not signed in. Run `rehearsal login` with an API key from the console's API keys page (or set REHEARSAL_API_KEY and REHEARSAL_URL).")
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in SERVER_MODULES:
            raise
        sys.exit(f"This command runs a Rehearsal server, which needs the server extra:\n  pip install 'rehearsal-kit[server]'\n(missing module: {exc.name})")


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("rehearsal-kit")
    except PackageNotFoundError:
        return "unknown (not installed)"


def _main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="rehearsal", description="Rehearse AI agents on a sandboxed copy of your application.")
    ap.add_argument("--version", action="version", version=f"rehearsal-kit {_version()}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("up", help="start the local control-plane database and apply migrations")
    sub.add_parser("migrate", help="apply database migrations")
    b = sub.add_parser("bootstrap", help="create an organisation, project, and admin API key")
    b.add_argument("--org", default="Local")
    b.add_argument("--project", default="default")
    users = sub.add_parser("users", help="console accounts (runs on the server)").add_subparsers(dest="sub", required=True)
    ua = users.add_parser("add", help="give a person access to a project's organisation")
    ua.add_argument("email")
    ua.add_argument("--name", default="")
    ua.add_argument("--project", required=True, help="project id, as printed by bootstrap")
    ua.add_argument("--role", choices=["owner", "admin", "member"], default="owner")
    ua.add_argument("--no-password", action="store_true", help="the person signs in with Google only")
    s = sub.add_parser("serve", help="run the API and console")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7800)
    w = sub.add_parser("worker", help="run a job worker")
    w.add_argument("--kinds", default="", help="comma-separated job kinds")
    w.add_argument("--once", action="store_true", help="exit when the queue is empty")
    sub.add_parser("openapi", help="print the OpenAPI document")
    lg = sub.add_parser("login", help="save the server URL and an API key for the CLI, SDK and MCP server")
    lg.add_argument("--url", default=None, help="Rehearsal server, for example https://rehearsal.example.com")
    lg.add_argument("--key", default=None, help="API key (rh_...); asked for when omitted, so it stays out of shell history")
    sub.add_parser("logout", help="forget the saved API key")
    sub.add_parser("mcp", help="run the MCP server for AI assistants (stdio; uses `rehearsal login`, or REHEARSAL_API_KEY and REHEARSAL_URL)")
    sk = sub.add_parser("skill", help="install the Rehearsal skill for Claude Code and other agents")
    sk.add_argument("action", choices=["install", "print"])
    sk.add_argument("--dir", default=None, help="skills folder (default ~/.claude/skills)")

    apps = sub.add_parser("apps").add_subparsers(dest="sub", required=True)
    apps.add_parser("import-catalog")
    apps.add_parser("list")
    add = apps.add_parser("add")
    add.add_argument("name")
    add.add_argument("--git")
    add.add_argument("--commit")
    add.add_argument("--path")
    add.add_argument("--image", action="append", default=[], help="component=image@sha256:...")
    add.add_argument("--policies-file")
    up = apps.add_parser("upload")
    up.add_argument("app_id")
    up.add_argument("archive")

    build = sub.add_parser("build", help="compile an application into a world")
    build.add_argument("app_id")
    build.add_argument("--model")
    build.add_argument("--budget", type=float)
    build.add_argument("--scenarios", type=int, default=8)
    build.add_argument("--watch", action="store_true")

    jobs = sub.add_parser("jobs").add_subparsers(dest="sub", required=True)
    for name in ("show", "watch", "pause", "resume", "stop", "retry"):
        jobs.add_parser(name).add_argument("job_id")

    worlds = sub.add_parser("worlds").add_subparsers(dest="sub", required=True)
    worlds.add_parser("list")
    worlds.add_parser("show").add_argument("wv_id")
    worlds.add_parser("scenarios").add_argument("wv_id")
    worlds.add_parser("validate").add_argument("wv_id")
    bnd = worlds.add_parser("bundle")
    bnd.add_argument("wv_id")
    bnd.add_argument("--include-images", action="store_true")

    prof = sub.add_parser("profiles").add_subparsers(dest="sub", required=True)
    prof.add_parser("list")
    pc = prof.add_parser("create")
    pc.add_argument("name")
    pc.add_argument("--prompt-file")
    pc.add_argument("--model")
    pc.add_argument("--external", action="store_true", help="actions come from your own agent through the API")

    ev = sub.add_parser("eval", help="evaluate agent profiles on a world version")
    ev.add_argument("wv_id")
    ev.add_argument("--profile", action="append", required=True)
    ev.add_argument("--split", action="append", default=[], help="train, dev or holdout; default every split")
    ev.add_argument("--repeats", type=int, default=None, help="default 2")
    ev.add_argument("--budget", type=float)
    ev.add_argument("--watch", action="store_true")

    runs = sub.add_parser("runs").add_subparsers(dest="sub", required=True)
    runs.add_parser("show").add_argument("run_id")
    runs.add_parser("watch").add_argument("run_id")
    runs.add_parser("episodes").add_argument("run_id")
    runs.add_parser("episode").add_argument("episode_id")
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("run_a")
    cmp_.add_argument("run_b", nargs="?")

    imp = sub.add_parser("improve", help="propose a revised agent profile from train/dev failures")
    imp.add_argument("profile_id")
    imp.add_argument("run_id")

    exp = sub.add_parser("export", help="export verified trajectories as a dataset")
    exp.add_argument("run_ids", nargs="+")
    exp.add_argument("--split", action="append", default=[])

    tr = sub.add_parser("train", help="train a model on a world with reinforcement learning (coming soon)")
    tr.add_argument("wv_id")
    tr.add_argument("--base-model", default="Qwen/Qwen3-1.7B")
    tr.add_argument("--rounds", type=int, default=2)
    tr.add_argument("--rollouts", type=int, default=4)
    tr.add_argument("--serve-url", default="http://127.0.0.1:8001/v1")

    art = sub.add_parser("artifacts").add_subparsers(dest="sub", required=True)
    art.add_parser("list")
    dl = art.add_parser("download")
    dl.add_argument("artifact_id")
    dl.add_argument("dest")

    sub.add_parser("prices", help="model prices from every source, for the configured model chains")

    exm = sub.add_parser("export-example", help="write examples/<app>/ from a published world version and its runs")
    exm.add_argument("wv_id")

    rep = sub.add_parser("export-replay", help="save a job's or run's recorded events (already redacted) as a replay file")
    rep.add_argument("stream", help="job_... or run_... id")
    rep.add_argument("dest")
    rep.add_argument("--episode", help="only this episode's events (runs)")

    run_b = sub.add_parser("run-bundle", help="start a world from an exported bundle on this machine")
    run_b.add_argument("bundle")

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not os.environ.get("REHEARSAL_DEBUG"):
        logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request drowns the output

    if args.cmd == "up":
        from importlib.resources import files

        compose = files("rehearsal").joinpath("assets/compose.yaml")
        subprocess.run(["docker", "compose", "-f", str(compose), "-p", "rehearsal", "up", "-d", "--wait"], check=True)
        from ..db.session import upgrade

        upgrade()
        print("database ready and migrated")
    elif args.cmd == "migrate":
        from ..db.session import upgrade

        upgrade()
    elif args.cmd == "bootstrap":
        from ..api.auth import bootstrap

        project_id, key = bootstrap(args.org, args.project)
        print(f"project: {project_id}\nadmin API key (shown once): {key}\nexport REHEARSAL_API_KEY={key}")
    elif args.cmd == "users":
        import getpass

        from ..api.auth import add_member

        password = None
        if not args.no_password:
            password = getpass.getpass("Password (10+ characters): ")
            if len(password) < 10 or password != getpass.getpass("Repeat: "):
                sys.exit("Passwords must match and be at least 10 characters.")
        add_member(args.email, args.name or args.email.split("@")[0], password, args.project, args.role)
        print(f"{args.email} can sign in to the console as {args.role} of project {args.project}.")
    elif args.cmd == "serve":
        import uvicorn

        # uvicorn trusts X-Forwarded-For/-Proto from FORWARDED_ALLOW_IPS (compose sets it for Caddy), so client addresses are real
        uvicorn.run("rehearsal.api.app:app", host=args.host, port=args.port, log_level="info", timeout_graceful_shutdown=5)
    elif args.cmd == "worker":
        from ..worker.main import run_worker

        run_worker([k for k in args.kinds.split(",") if k] or None, once=args.once)
    elif args.cmd == "login":
        import getpass

        from .client import DEFAULT_URL, Rehearsal, save_login, saved_login

        login = saved_login()
        url = (args.url or os.environ.get("REHEARSAL_URL") or input(f"Rehearsal server [{login.get('url') or DEFAULT_URL}]: ").strip()
               or login.get("url") or DEFAULT_URL).rstrip("/")
        key = (args.key or getpass.getpass("API key (create one on the console's API keys page): ")).strip()
        if not key.startswith("rh_"):
            sys.exit("That is not a Rehearsal API key; keys start with rh_.")
        me = Rehearsal(api_key=key, base_url=url).get("/v1/me")  # fails with a clear message on a wrong key or URL
        path = save_login(url, key)
        print(f"Signed in to {me.get('organization') or 'your workspace'} (project {me.get('project')}) at {url}. Saved to {path}.")
    elif args.cmd == "logout":
        from .client import config_path

        config_path().unlink(missing_ok=True)
        print("Signed out: the saved API key is removed.")
    elif args.cmd == "mcp":
        try:
            from .mcp import main as mcp_main

            mcp_main()
        except ModuleNotFoundError as exc:
            sys.exit(f"The MCP server needs the mcp extra:\n  pip install 'rehearsal-kit[mcp]'\n(missing module: {exc.name})")
    elif args.cmd == "skill":
        from importlib.resources import files

        skill = files("rehearsal").joinpath("assets/skill")
        if args.action == "print":
            print(skill.joinpath("SKILL.md").read_text())
        else:
            target = Path(args.dir or Path.home() / ".claude" / "skills") / "rehearsal"
            (target / "references").mkdir(parents=True, exist_ok=True)
            for rel in ["SKILL.md", *(f"references/{f.name}" for f in skill.joinpath("references").iterdir() if f.name.endswith(".md"))]:
                (target / rel).write_text(skill.joinpath(rel).read_text())
            print(f"installed {target}")
    elif args.cmd == "openapi":
        from ..api.app import app

        print(json.dumps(app.openapi(), indent=1))
    elif args.cmd == "apps":
        c = _client()
        if args.sub == "import-catalog":
            _print([{k: a[k] for k in ("id", "name", "notes")} for a in c.applications.import_catalog()])
        elif args.sub == "list":
            _print([{k: a[k] for k in ("id", "name", "source", "notes")} for a in c.applications.list()])
        elif args.sub == "add":
            if args.git:
                source = {"kind": "git", "url": args.git, "commit": args.commit}
            elif args.path:
                source = {"kind": "local_path", "path": os.path.abspath(args.path)}
            else:
                source = {"kind": "upload"}
            images = dict(i.split("=", 1) for i in args.image)
            policies = Path(args.policies_file).read_text() if args.policies_file else ""
            _print(c.applications.create(args.name, source, images, policies))
        elif args.sub == "upload":
            _print(c.applications.upload_source(args.app_id, args.archive))
    elif args.cmd == "build":
        c = _client()
        opts: dict[str, Any] = {"scenario_target": args.scenarios}
        if args.model:
            opts["model"] = args.model
        if args.budget is not None:
            opts["budget_usd"] = args.budget
        res = c.worlds.build(args.app_id, **opts)
        _print(res)
        if args.watch:
            _watch(c.jobs.events(res["job_id"]))
    elif args.cmd == "jobs":
        c = _client()
        if args.sub == "show":
            _print(c.jobs.get(args.job_id))
        elif args.sub == "watch":
            _watch(c.jobs.events(args.job_id))
        else:
            _print(c.jobs.command(args.job_id, args.sub))
    elif args.cmd == "worlds":
        c = _client()
        if args.sub == "list":
            _print(c.worlds.list())
        elif args.sub == "show":
            _print(c.worlds.version(args.wv_id))
        elif args.sub == "scenarios":
            _print([{k: s[k] for k in ("id", "slug", "family", "split", "status")} for s in c.worlds.scenarios(args.wv_id)])
        elif args.sub == "validate":
            _print(c.worlds.validate(args.wv_id))
        elif args.sub == "bundle":
            _print(c.worlds.bundle(args.wv_id, args.include_images))
    elif args.cmd == "profiles":
        c = _client()
        if args.sub == "list":
            _print([{k: p[k] for k in ("id", "name", "version", "created_by")} for p in c.profiles.list()])
        else:
            prompt = Path(args.prompt_file).read_text() if args.prompt_file else ""
            extra: dict[str, Any] = {"driver": "external"} if args.external else {}
            if args.model:
                extra["model"] = args.model
            _print(c.profiles.create(args.name, prompt, **extra))
    elif args.cmd == "eval":
        c = _client()
        res = c.evaluations.create(args.wv_id, args.profile, args.split or None, args.repeats, **({"budget_usd": args.budget} if args.budget is not None else {}))
        _print(res)
        if args.watch:
            _watch(c.runs.events(res["run_id"]))
            _print(c.runs.get(res["run_id"])["summary"])
    elif args.cmd == "runs":
        c = _client()
        if args.sub == "show":
            _print(c.runs.get(args.run_id))
        elif args.sub == "watch":
            _watch(c.runs.events(args.run_id))
        elif args.sub == "episodes":
            _print([{k: e[k] for k in ("id", "scenario", "split", "profile", "status", "reward", "termination")} for e in c.runs.episodes(args.run_id)])
        else:
            _print(c.runs.episode(args.episode_id))
    elif args.cmd == "compare":
        _print(_client().evaluations.compare(args.run_a, args.run_b))
    elif args.cmd == "improve":
        _print(_client().post("/v1/improvements", {"profile_id": args.profile_id, "run_id": args.run_id}))
    elif args.cmd == "export":
        _print(_client().post("/v1/dataset-exports", {"run_ids": args.run_ids, "splits": args.split or ["train"]}))
    elif args.cmd == "train":
        sys.exit("Training a model on your practice worlds (reinforcement learning) is coming soon. Every episode already ends with a verified score from the application's database; today you can export verified episodes as a dataset with `rehearsal export`, and improve an agent's instructions with `rehearsal improve`.")
    elif args.cmd == "artifacts":
        c = _client()
        if args.sub == "list":
            _print(c.get("/v1/artifacts"))
        else:
            import tempfile

            dest = Path(args.dest)
            with c.http.stream("GET", f"/v1/artifacts/{args.artifact_id}/download") as resp:
                resp.raise_for_status()
                with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as fh:
                    tmp = Path(fh.name)
                    try:
                        for chunk in resp.iter_bytes():
                            fh.write(chunk)
                    except BaseException:
                        tmp.unlink(missing_ok=True)
                        raise
                try:
                    tmp.replace(dest)
                finally:
                    tmp.unlink(missing_ok=True)
            print(f"saved {args.dest}")
    elif args.cmd == "prices":
        from .. import pricing
        from ..config import settings as cfg

        c = cfg()
        rows = pricing.report({"compiler": c.model_compiler, "agent": c.model_agent, "participant": c.model_participant})
        for r in rows:
            b = r["billing"]
            m = r["market"]
            charged = f"${b['input_per_m']:.3f}/${b['output_per_m']:.3f} per 1M ({b['source']}, {b['as_of']})" if b else "unknown (add it to pricing.yaml)"
            ref = f"{m['hosts']} hosts, input ${m['input_per_m']['min']:.3f}-{m['input_per_m']['max']:.3f}, output ${m['output_per_m']['min']:.3f}-{m['output_per_m']['max']:.3f}" if m else "no market listing"
            print(f"{r['purpose']:<12} {r['provider']}:{r['model']}\n  charged at: {charged}\n  market:     {ref}")
    elif args.cmd == "export-example":
        from .examples import export_example

        _print(export_example(_client(), args.wv_id))
    elif args.cmd == "export-replay":
        c = _client()
        events, cursor = [], 0
        while True:
            page = c.get(f"/v1/streams/{args.stream}/events/page", params={"cursor": cursor, "limit": 2000})
            if not page:
                break
            events += page
            cursor = page[-1]["event_id"]
        keep = {"compiler.tool", "compiler.note", "compiler.submit.accepted", "compiler.submit.rejected", "compiler.phase.started", "compiler.phase.completed",
                "compiler.repair", "compiler.validation", "world.published", "episode.started", "customer.message", "agent.reply", "message.sent",
                "notification", "agent.decision", "goal.revised", "fault.injected", "permission.changed", "action.succeeded", "action.failed",
                "action.unknown", "action.rejected", "episode.claimed_complete", "episode.finished"}
        events = [e for e in events if e["type"] in keep and (not args.episode or e.get("episode_id") == args.episode)]
        Path(args.dest).parent.mkdir(parents=True, exist_ok=True)
        Path(args.dest).write_text(json.dumps({"stream": args.stream, "events": events}, default=str))
        print(f"saved {len(events)} events to {args.dest}")
    elif args.cmd == "run-bundle":
        ap.error("run-bundle is not implemented in this release; use a published world through the API")


if __name__ == "__main__":
    main(sys.argv[1:])
