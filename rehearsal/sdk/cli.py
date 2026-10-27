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

from .client import DEFAULT_URL

NOT_SIGNED_IN = (f"Not signed in. Run `rehearsal login`: it signs in to Rehearsal at {DEFAULT_URL} through your browser "
                 "(add `--url <address>` for a server of your own). In CI, set REHEARSAL_API_KEY.")


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
        from .client import saved_login

        url = os.environ.get("REHEARSAL_URL") or saved_login().get("url") or DEFAULT_URL
        sys.exit(f"Cannot reach Rehearsal at {url} ({exc.__class__.__name__}). Check the URL (`rehearsal login --url ...`) and that the server is running.")
    except httpx.TimeoutException:
        sys.exit("Rehearsal did not answer in time. Try again; long work runs as jobs, so check 'rehearsal jobs show JOB_ID'.")
    except ValueError as exc:
        if "REHEARSAL_API_KEY" not in str(exc):
            raise
        sys.exit(NOT_SIGNED_IN)
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in SERVER_MODULES:
            raise
        sys.exit(f"This command runs a Rehearsal server, which needs the server extra:\n  pip install 'rehearsal-kit[server]'\n(missing module: {exc.name})")


def _db_host(url: str) -> str:
    from sqlalchemy.engine import make_url

    try:
        return make_url(url).host or ""
    except Exception:  # noqa: BLE001 - only for a log line
        return "unknown"


def _server(explicit: str | None) -> str:
    from .client import _env, saved_login

    return (explicit or _env("REHEARSAL_URL") or saved_login().get("url") or DEFAULT_URL).rstrip("/")


def _signed_in(url: str, key: str) -> None:
    from .client import Rehearsal, save_login

    me = Rehearsal(api_key=key, base_url=url).get("/v1/me")  # a wrong key or URL fails here with a clear message
    path = save_login(url, key)
    print(f"\n\u2713 Signed in to {me.get('organization') or 'your workspace'} (project {me.get('project')}) at {url}.")
    print(f"  Saved to {path} (readable by you only). The CLI, the Python SDK and the MCP server use it.")
    print("  Next: rehearsal worlds list")


def _login(args: Any) -> None:
    """Browser sign-in by default: the terminal shows a code, the console approves it, the terminal receives a key.
    --with-key pastes a key instead, for servers and CI where no browser is at hand."""
    import getpass
    import socket
    import time
    import webbrowser

    import httpx

    url = _server(args.url)
    print(f"Signing in to Rehearsal at {url}" + ("" if args.url else "  (another server: rehearsal login --url <address>)"))
    if args.key or args.with_key:
        key = (args.key or getpass.getpass("Paste an API key from the console's API keys page (input is hidden): ")).strip()
        if not key.startswith("rh_"):
            sys.exit("That is not a Rehearsal API key; keys start with rh_.")
        return _signed_in(url, key)

    client = f"{getpass.getuser()}@{socket.gethostname()}"
    try:
        r = httpx.post(f"{url}/v1/cli/logins", json={"client": client}, timeout=30)
    except httpx.HTTPError as exc:
        sys.exit(f"Cannot reach {url} ({exc.__class__.__name__}). Check the address, or use --url.")
    if r.status_code == 404:  # a server older than browser sign-in
        print("This server does not offer browser sign-in yet; paste a key instead.")
        args.with_key = True
        return _login(args)
    if r.status_code >= 400:
        sys.exit(f"The server refused to start a sign-in ({r.status_code}): {r.text[:200]}")
    start = r.json()
    print("\nApprove this sign-in in your browser:")
    print(f"  {start['verification_url']}")
    print(f"\nConfirmation code: {start['user_code']}  (the browser shows the same code)")
    if not args.no_browser:
        try:
            if webbrowser.open(start["verification_url"]):
                print("A browser window is opening. If it does not, open the link above.")
        except webbrowser.Error:
            pass
    print("\nWaiting for approval (Ctrl+C to cancel)", end="", flush=True)
    deadline = time.monotonic() + start["expires_in"]
    try:
        while time.monotonic() < deadline:
            time.sleep(start.get("interval", 2))
            try:
                poll = httpx.post(f"{url}/v1/cli/logins/poll", json={"device_code": start["device_code"]}, timeout=30).json()
            except (httpx.HTTPError, ValueError):
                print("!", end="", flush=True)  # a network blip: keep waiting
                continue
            if poll.get("status") == "pending":
                print(".", end="", flush=True)
                continue
            print()
            if poll.get("status") == "approved":
                return _signed_in(url, poll["api_key"])
            if poll.get("status") == "denied":
                sys.exit("The sign-in was denied in the browser. Nothing was saved.")
            sys.exit("The sign-in request expired or was already used. Run rehearsal login again.")
    except KeyboardInterrupt:
        print()
        sys.exit("Cancelled. Nothing was saved.")
    print()
    sys.exit("No approval within 10 minutes. Run rehearsal login again.")


def _whoami() -> None:
    from .client import Rehearsal, _env, config_path, saved_login

    source = "environment (REHEARSAL_API_KEY)" if _env("REHEARSAL_API_KEY") else (f"saved sign-in ({config_path()})" if saved_login() else None)
    if source is None:
        sys.exit(NOT_SIGNED_IN)
    c = Rehearsal()
    me = c.get("/v1/me")
    print(f"Server:     {c.base_url}")
    print(f"Workspace:  {me.get('organization')} (project {me.get('project')})" + (f", {me['plan']} plan" if me.get("plan") else ""))
    print(f"Key:        rh_{c.api_key.split('_')[1]}_\u2026  access: {', '.join(me.get('scopes') or [])}")
    print(f"Signed in:  {source}")


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("rehearsal-kit")
    except PackageNotFoundError:
        return "unknown (not installed)"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # a mistyped command gets a suggestion, not the full list of choices
        import difflib
        import re

        m = re.search(r"argument <(?:command|action)>: invalid choice: '([^']*)' \(choose from (.*)\)", message)
        if m:
            choices = [c.strip().strip("'") for c in m.group(2).split(",")]
            close = difflib.get_close_matches(m.group(1), choices, n=1)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            self.exit(2, f"{self.prog}: unknown command '{m.group(1)}'.{hint} Run '{self.prog} --help' to see every command.\n")
        super().error(message)


def _main(argv: list[str] | None = None) -> None:
    ap = _Parser(prog="rehearsal", usage="rehearsal <command> [options]", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"rehearsal-kit {_version()}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>", help=argparse.SUPPRESS, prog="rehearsal")
    summaries: dict[str, str] = {}

    def cmd(name: str, help: str, **kw: Any) -> argparse.ArgumentParser:  # noqa: A002 - mirrors argparse's own keyword
        summaries[name] = help
        return sub.add_parser(name, help=argparse.SUPPRESS, description=help[0].upper() + help[1:] + ".", **kw)

    def actions(parser: argparse.ArgumentParser) -> Any:
        return parser.add_subparsers(dest="sub", required=True, metavar="<action>", title="actions")

    cmd("up", "apply database migrations; starts a local database in Docker only when no cloud database is set")
    cmd("migrate", "apply database migrations")
    b = cmd("bootstrap", "create an organisation, project, and admin API key")
    b.add_argument("--org", default="Local")
    b.add_argument("--project", default="default")
    users = actions(cmd("users", "console accounts (runs on the server)"))
    ua = users.add_parser("add", help="give a person access to a project's organisation")
    ua.add_argument("email")
    ua.add_argument("--name", default="")
    ua.add_argument("--project", required=True, help="project id, as printed by bootstrap")
    ua.add_argument("--role", choices=["owner", "admin", "member"], default="owner")
    ua.add_argument("--no-password", action="store_true", help="the person signs in with Google only")
    s = cmd("serve", "run the API and console")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7800)
    w = cmd("worker", "run a job worker")
    w.add_argument("--kinds", default="", help="comma-separated job kinds")
    w.add_argument("--once", action="store_true", help="exit when the queue is empty")
    cmd("openapi", "print the OpenAPI document")
    lg = cmd("login", "sign in: approve this terminal in your browser, or paste an API key")
    lg.add_argument("--url", default=None, help="Rehearsal server (default: REHEARSAL_URL, the last server you signed in to, or %s)" % DEFAULT_URL)
    lg.add_argument("--with-key", action="store_true", help="paste an API key instead of approving in the browser (servers, CI)")
    lg.add_argument("--key", default=None, help=argparse.SUPPRESS)  # still accepted, but keys on the command line end up in shell history
    lg.add_argument("--no-browser", action="store_true", help="print the approval link instead of opening a browser")
    cmd("logout", "forget the saved sign-in on this machine")
    cmd("whoami", "show the server, workspace and key this machine uses")
    cmd("mcp", "run the MCP server for AI assistants (stdio; uses your rehearsal login)")
    sk = cmd("skill", "install the Rehearsal skill for Claude Code and other agents")
    sk.add_argument("action", choices=["install", "print"])
    sk.add_argument("--dir", default=None, help="skills folder (default ~/.claude/skills)")

    apps = actions(cmd("apps", "add, list and upload applications"))
    apps.add_parser("import-catalog", help="register the bundled catalog of open-source applications")
    apps.add_parser("list", help="applications in this workspace")
    add = apps.add_parser("add", help="add an application from a git repository or a local folder")
    add.add_argument("name")
    add.add_argument("--git")
    add.add_argument("--commit")
    add.add_argument("--path")
    add.add_argument("--image", action="append", default=[], help="component=image@sha256:...")
    add.add_argument("--policies-file")
    up = apps.add_parser("upload", help="upload a .tar.gz of an application's source")
    up.add_argument("app_id")
    up.add_argument("archive")

    build = cmd("build", "compile an application into a world")
    build.add_argument("app_id")
    build.add_argument("--model")
    build.add_argument("--budget", type=float)
    build.add_argument("--scenarios", type=int, default=8)
    build.add_argument("--watch", action="store_true")

    jobs = actions(cmd("jobs", "follow and control builds and other long jobs"))
    for name in ("show", "watch", "pause", "resume", "stop", "retry"):
        jobs.add_parser(name, help=f"{name} a job").add_argument("job_id")

    worlds = actions(cmd("worlds", "list practice worlds, their jobs, re-checks and bundles"))
    worlds.add_parser("list", help="worlds and their versions")
    worlds.add_parser("show", help="one world version").add_argument("wv_id")
    worlds.add_parser("scenarios", help="the jobs of a world version").add_argument("wv_id")
    worlds.add_parser("validate", help="re-check every job of a published world").add_argument("wv_id")
    bnd = worlds.add_parser("bundle", help="export a portable world bundle")
    bnd.add_argument("wv_id")
    bnd.add_argument("--include-images", action="store_true")

    prof = actions(cmd("profiles", "list and create agent profiles (agent versions)"))
    prof.add_parser("list", help="agent profiles and versions")
    pc = prof.add_parser("create", help="create an agent profile")
    pc.add_argument("name")
    pc.add_argument("--prompt-file")
    pc.add_argument("--model")
    pc.add_argument("--external", action="store_true", help="actions come from your own agent through the API")

    ev = cmd("eval", "evaluate agent profiles on a world version")
    ev.add_argument("wv_id")
    ev.add_argument("--profile", action="append", required=True)
    ev.add_argument("--split", action="append", default=[], help="train, dev or holdout; default every split")
    ev.add_argument("--repeats", type=int, default=None, help="default 2")
    ev.add_argument("--budget", type=float)
    ev.add_argument("--watch", action="store_true")

    runs = actions(cmd("runs", "follow runs and read their episodes"))
    runs.add_parser("show", help="status and scores of a run").add_argument("run_id")
    runs.add_parser("watch", help="follow a run live").add_argument("run_id")
    runs.add_parser("episodes", help="one line per episode").add_argument("run_id")
    runs.add_parser("episode", help="what happened in one episode").add_argument("episode_id")
    cmp_ = cmd("compare", "compare agents within a run, or two runs on one world version")
    cmp_.add_argument("run_a")
    cmp_.add_argument("run_b", nargs="?")

    imp = cmd("improve", "propose a revised agent profile from train/dev failures")
    imp.add_argument("profile_id")
    imp.add_argument("run_id")

    fix = cmd("autofix", "fix an agent in rounds, keep only versions that verify more, prove the best on held-out jobs")
    fix.add_argument("profile_id")
    fix.add_argument("run_id", help="a finished run with train/dev episodes for this agent")
    fix.add_argument("--rounds", type=int, default=3, help="1 to 5 (default 3)")
    fix.add_argument("--repeats", type=int, default=1, help="episodes per job in each rehearsal, 1 to 5 (default 1)")
    fix.add_argument("--watch", action="store_true")

    gate = cmd("gate", "pass or fail an agent change in CI: rehearse it, next to a baseline, and judge the result")
    gate.add_argument("wv_id", nargs="?", help="the published world version to rehearse on")
    gate.add_argument("--profile", help="the agent profile to test")
    gate.add_argument("--prompt-file", help="test a version of --name with these instructions (reused when unchanged)")
    gate.add_argument("--name", help="the agent's name, with --prompt-file or --baseline-file")
    gate.add_argument("--baseline", help="a profile to rehearse side by side; the change may not do worse")
    gate.add_argument("--baseline-file", help="the baseline as an instructions file, for example the one on the main branch")
    gate.add_argument("--split", action="append", default=[], help="train, dev or holdout; default every split")
    gate.add_argument("--repeats", type=int, default=1, help="attempts at each job (default 1)")
    gate.add_argument("--min-success", type=float, help="fail below this verified success rate, 0 to 1")
    gate.add_argument("--max-violations", type=int, default=0, help="fail above this many episodes with a rule violation (default 0)")
    gate.add_argument("--tolerance", type=float, default=0.0, help="how far below the baseline's success rate still passes, 0 to 1")
    gate.add_argument("--budget", type=float, help="model spend in US dollars at which the run stops itself")
    gate.add_argument("--run", help="judge this finished run instead of starting one")
    gate.add_argument("--timeout", type=float, default=90, help="minutes to wait for the run (default 90)")
    gate.add_argument("--report", help="append the Markdown report to this file, for example $GITHUB_STEP_SUMMARY")

    exp = cmd("export", "export verified trajectories as a dataset")
    exp.add_argument("run_ids", nargs="+")
    exp.add_argument("--split", action="append", default=[])

    tr = cmd("train", "train a model on a world with reinforcement learning")
    tr.add_argument("wv_id")
    tr.add_argument("--base-model", default="Qwen/Qwen3-1.7B")
    tr.add_argument("--rounds", type=int, default=2)
    tr.add_argument("--rollouts", type=int, default=4)
    tr.add_argument("--serve-url", default="http://127.0.0.1:8001/v1")

    art = actions(cmd("artifacts", "list and download exported files"))
    art.add_parser("list", help="exported files")
    dl = art.add_parser("download", help="download one exported file")
    dl.add_argument("artifact_id")
    dl.add_argument("dest")

    cmd("prices", "model prices from every source, for the configured model chains")

    exm = cmd("export-example", "write examples/<app>/ from a published world version and its runs")
    exm.add_argument("wv_id")

    rep = cmd("export-replay", "save a job's or run's recorded events (already redacted) as a replay file")
    rep.add_argument("stream", help="job_... or run_... id")
    rep.add_argument("dest")
    rep.add_argument("--episode", help="only this episode's events (runs)")

    run_b = cmd("run-bundle", "start a world from an exported bundle on your own machine")
    run_b.add_argument("bundle")

    groups = [
        ("Start", ["login", "whoami", "logout"]),
        ("Applications and worlds", ["apps", "build", "worlds", "jobs"]),
        ("Agents and evaluations", ["profiles", "eval", "runs", "compare", "improve", "autofix", "gate"]),
        ("Data", ["export", "artifacts", "export-example", "export-replay"]),
        ("AI assistants", ["mcp", "skill"]),
        ("Run your own server", ["serve", "worker", "up", "migrate", "bootstrap", "users", "openapi", "prices"]),
        ("Coming soon", ["train", "run-bundle"]),
    ]
    assert sorted(n for _, names in groups for n in names) == sorted(summaries), "every command belongs to one help group"
    width = max(map(len, summaries)) + 2
    ap.description = "Rehearse AI agents on a sandboxed copy of your application.\n\n" + "\n\n".join(
        f"{title}:\n" + "\n".join(f"  {n:<{width}}{summaries[n]}" for n in names) for title, names in groups)
    ap.epilog = "Get started: rehearsal login, then rehearsal worlds list.\nHelp for one command: rehearsal <command> --help"
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not os.environ.get("REHEARSAL_DEBUG"):
        logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request drowns the output

    if args.cmd == "up":
        from importlib.resources import files

        from ..config import settings
        from ..db.session import upgrade

        host = _db_host(settings().database_url)
        if host in ("127.0.0.1", "localhost", "::1", ""):  # no cloud database configured: run one locally in Docker
            compose = files("rehearsal").joinpath("assets/compose.yaml")
            subprocess.run(["docker", "compose", "-f", str(compose), "-p", "rehearsal", "up", "-d", "--wait"], check=True)
        upgrade()
        print(f"database ready and migrated: {host or 'local'}" + ("" if host in ("127.0.0.1", "localhost", "::1", "") else " (cloud; no local database started)"))
    elif args.cmd == "migrate":
        from ..db.session import upgrade

        upgrade()
    elif args.cmd == "bootstrap":
        from ..api.auth import bootstrap

        from ..config import settings

        project_id, key = bootstrap(args.org, args.project)
        print(f"project: {project_id}\nadmin API key (shown once): {key}\nexport REHEARSAL_URL={settings().public_url}\nexport REHEARSAL_API_KEY={key}")
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

        from ..config import settings

        print(f"Rehearsal API on http://{args.host}:{args.port}, database {_db_host(settings().database_url)}", flush=True)

        # uvicorn trusts X-Forwarded-For/-Proto from FORWARDED_ALLOW_IPS (compose sets it for Caddy), so client addresses are real
        uvicorn.run("rehearsal.api.app:app", host=args.host, port=args.port, log_level="info", timeout_graceful_shutdown=5)
    elif args.cmd == "worker":
        from ..worker.main import run_worker

        run_worker([k for k in args.kinds.split(",") if k] or None, once=args.once)
    elif args.cmd == "login":
        _login(args)
    elif args.cmd == "logout":
        from .client import config_path, saved_login

        if not saved_login():
            print("Not signed in on this machine; nothing to remove.")
        else:
            config_path().unlink(missing_ok=True)
            print("Signed out. The saved key is removed from this machine; revoke it on the console's API keys page to disable it everywhere.")
    elif args.cmd == "whoami":
        _whoami()
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
    elif args.cmd == "autofix":
        c = _client()
        res = c.profiles.autofix(args.profile_id, args.run_id, rounds=args.rounds, repeats=args.repeats)
        _print(res)
        if args.watch:
            _watch(c.jobs.events(res["job_id"]))
            _print((c.jobs.get(res["job_id"]).get("result")) or {})
    elif args.cmd == "gate":
        import httpx

        from .client import RehearsalError
        from .gate import UNFINISHED, run as run_gate

        try:
            code = run_gate(_client(), args)
        except (RehearsalError, httpx.HTTPError) as exc:  # the check could not run, which is not the agent failing
            print(f"The gate could not run: {exc}", file=sys.stderr)
            code = UNFINISHED
        sys.exit(code)
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
        rows = pricing.report({"compiler": c.model_compiler, "reasoner": c.model_reasoner, "agent": c.model_agent, "participant": c.model_participant, "improver": c.model_improver})
        for r in rows:
            b = r["billing"]
            m = r["market"]
            charged = f"${b['input_per_m']:.3f}/${b['output_per_m']:.3f} per 1M ({b['source']}, {b['as_of']})" if b else "unknown (add it to pricing.yaml)"
            ref = f"{m['hosts']} hosts, input ${m['input_per_m']['min']:.3f}-{m['input_per_m']['max']:.3f}, output ${m['output_per_m']['min']:.3f}-{m['output_per_m']['max']:.3f}" if m else "no market listing"
            mode = {True: " (thinking on)", False: " (thinking off)"}.get(r.get("thinking"), "")
            print(f"{r['purpose']:<12} {r['provider']}:{r['model']}{mode}\n  charged at: {charged}\n  market:     {ref}")
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
        print(f"saved {len(events)} events to {args.dest}" + ("" if events else
              " (a replay holds build and episode activity; this job or run has none yet)"))
    elif args.cmd == "run-bundle":
        sys.exit("Starting a world from a bundle on your own machine is coming soon. Today, evaluate the published world "
                 "through the server: rehearsal eval <world_version_id> --profile <agent_id>.")


if __name__ == "__main__":
    main(sys.argv[1:])
