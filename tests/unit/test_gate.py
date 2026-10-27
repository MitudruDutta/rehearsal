"""`rehearsal gate`: a CI check that passes only when the agent verifies enough and does no worse than its baseline."""

from types import SimpleNamespace

from rehearsal.sdk import gate


def agg(rate, violations=0, false_done=0, dupes=0, finished=6):
    return {"success_rate": rate, "successes": round((rate or 0) * finished), "finished": finished, "hard_violation_episodes": violations,
            "false_completions": false_done, "duplicate_effects": dupes, "environment_errors": 0}


def summary(**profiles):
    return {"profiles": {k.replace("_", "@"): {"overall": v} for k, v in profiles.items()}}


def test_thresholds_and_baseline_decide():
    s = summary(agent_v2=agg(0.67), agent_v1=agg(0.5))
    assert gate.verdict(s, "agent@v2", "agent@v1", min_success=0.6)[0]
    assert not gate.verdict(s, "agent@v2", "agent@v1", min_success=0.8)[0]
    assert not gate.verdict(summary(agent_v2=agg(0.5), agent_v1=agg(0.67)), "agent@v2", "agent@v1")[0]  # a regression
    assert gate.verdict(summary(agent_v2=agg(0.5), agent_v1=agg(0.67)), "agent@v2", "agent@v1", tolerance=0.2)[0]
    ok, checks = gate.verdict(summary(agent_v2=agg(0.83, dupes=1), agent_v1=agg(0.5)), "agent@v2", "agent@v1")
    assert not ok and any(not passed and "duplicate" in text for passed, text in checks)  # more verified, but a new duplicate
    assert not gate.verdict(summary(agent_v2=agg(1.0, violations=1)), "agent@v2")[0]  # rule violations: none allowed by default
    assert not gate.verdict(summary(agent_v2=agg(None, finished=0)), "agent@v2")[0]  # nothing scored is not a pass


class FakeClient:
    base_url = "https://rehearsal.example"

    def __init__(self, existing, run_summary, status="finished"):
        self.existing, self.run_summary, self.status = existing, run_summary, status
        self.created, self.evaluated = [], []
        self.profiles = SimpleNamespace(list=lambda: self.existing, create=self.create)
        self.evaluations = SimpleNamespace(create=self.evaluate)
        self.runs = SimpleNamespace(get=lambda run_id: {"status": self.status, "summary": self.run_summary})

    def create(self, name, prompt):
        p = {"id": f"p{len(self.existing) + 1}", "name": name, "version": len(self.existing) + 1, "spec": {"system_prompt": prompt}}
        self.existing.append(p)
        self.created.append(p)
        return p

    def evaluate(self, wv, profile_ids, splits, repeats, **fields):
        self.evaluated.append(profile_ids)
        return {"run_id": "run_1", "episodes": 6 * len(profile_ids)}


def args(tmp_path, **kw):
    base = dict(wv_id="wv", profile=None, prompt_file=None, name="agent", baseline=None, baseline_file=None, split=[], repeats=1,
                min_success=None, max_violations=0, tolerance=0.0, budget=None, run=None, timeout=1, report=None)
    return SimpleNamespace(**{**base, **kw})


def test_a_changed_prompt_runs_next_to_main_and_writes_the_report(tmp_path):
    (tmp_path / "main.md").write_text("Be polite.")
    (tmp_path / "pr.md").write_text("Be polite. Read back the latest request.")
    c = FakeClient([{"id": "p1", "name": "agent", "version": 1, "spec": {"system_prompt": "Be polite."}}],
                   summary(agent_v2=agg(0.67), agent_v1=agg(0.5)))
    out = tmp_path / "summary.md"
    code = gate.run(c, args(tmp_path, prompt_file=str(tmp_path / "pr.md"), baseline_file=str(tmp_path / "main.md"), report=str(out)))
    assert code == gate.PASSED
    assert [p["version"] for p in c.created] == [2] and c.evaluated == [["p2", "p1"]]  # main's version was reused, not copied
    text = out.read_text()
    assert "Rehearsal gate: passed" in text and "| Verified success | 67% (4/6) | 50% (3/6) |" in text and "app/run/?id=run_1" in text


def test_an_unchanged_prompt_is_not_compared_with_itself(tmp_path):
    (tmp_path / "a.md").write_text("Be polite.")
    c = FakeClient([{"id": "p1", "name": "agent", "version": 1, "spec": {"system_prompt": "Be polite."}}], summary(agent_v1=agg(0.5)))
    assert gate.run(c, args(tmp_path, prompt_file=str(tmp_path / "a.md"), baseline_file=str(tmp_path / "a.md"), min_success=0.6)) == gate.FAILED
    assert c.created == [] and c.evaluated == [["p1"]]


def test_a_run_that_does_not_finish_is_neither_pass_nor_fail(tmp_path, capsys):
    c = FakeClient([], {}, status="failed")
    c.get = lambda path: {"id": "p9", "name": "agent", "version": 9}
    assert gate.run(c, args(tmp_path, profile="p9")) == gate.UNFINISHED
    assert "did not finish (failed)" in capsys.readouterr().err



def test_a_refused_run_exits_2_not_1(monkeypatch, capsys):
    import httpx
    import pytest

    from rehearsal.sdk import Rehearsal, cli
    from rehearsal.sdk import client as sdk

    def server(request):
        if request.method == "POST":
            return httpx.Response(402, json={"detail": "the plan's episodes are used up"})
        return httpx.Response(200, json={"id": "p1", "name": "agent", "version": 1})

    with httpx.Client(base_url="https://rehearsal.test", transport=httpx.MockTransport(server)) as http:
        monkeypatch.setattr(sdk.httpx, "Client", lambda **kwargs: http)
        monkeypatch.setattr(cli, "_client", lambda: Rehearsal(api_key="k", base_url="https://rehearsal.test"))
        with pytest.raises(SystemExit) as stop:
            cli.main(["gate", "wv", "--profile", "p1"])
    assert stop.value.code == gate.UNFINISHED  # a refused run is not the agent failing
    err = capsys.readouterr().err
    assert "could not run" in err and "402" in err
