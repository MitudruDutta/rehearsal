"""The fix-my-agent loop: keep only versions that verify more, learn from rejected attempts, prove on held-out jobs."""

from types import SimpleNamespace

import pytest

from rehearsal.worker import autofix


def agg(rate, finished=6, violations=0, false_done=0):
    return {"success_rate": rate, "finished": finished, "hard_violation_episodes": violations, "false_completions": false_done}


def test_better_needs_more_verified_and_no_new_problems():
    base = agg(0.5)
    assert autofix.better(agg(0.67), base)
    assert not autofix.better(agg(0.5), base)  # equal is not better
    assert not autofix.better(agg(0.83, violations=1), base)  # more verified, but a new rule violation
    assert not autofix.better(agg(0.83, false_done=1), base)
    assert not autofix.better(agg(None, finished=0), base)  # nothing scored (environment errors)


def test_better_compares_problems_per_episode_when_runs_differ_in_size():
    base = agg(0.5, finished=12, violations=2)  # the starting run: two attempts per job
    assert autofix.better(agg(0.67, finished=6, violations=1), base)  # same share of episodes with a violation
    assert not autofix.better(agg(0.67, finished=6, violations=2), base)  # same count, twice the share


class Loop:
    """A fake world: proposals, rehearsals and scores scripted per version, with a recorded checkpoint."""

    def __init__(self, monkeypatch, practice, holdout=None):
        self.practice, self.holdout = practice, holdout or {}
        self.proposals, self.runs, self.logs, self.saved = [], [], [], []
        self.ctx = SimpleNamespace(payload={"profile_id": "p1", "run_id": "r0", "world_version_id": "wv", "rounds": 3, "repeats": 1},
                                   checkpoint={}, job_id="job", check=lambda: None,
                                   log=lambda t, m, d=None: self.logs.append((t, m)), save_checkpoint=self.saved.append)
        monkeypatch.setattr(autofix, "_version", lambda pid: int(pid[1:]))
        monkeypatch.setattr(autofix.improve, "propose", self.propose)
        monkeypatch.setattr(autofix.improve, "score", self.score)
        monkeypatch.setattr(autofix, "_new_run", self.new_run)
        monkeypatch.setattr(autofix, "_rehearse", lambda ctx, run_id: self.runs.append(run_id))

    def propose(self, ctx, profile_id, run_id, *, rejected=None):
        n = len(self.proposals) + 2
        self.proposals.append({"from": profile_id, "run": run_id, "rejected": list(rejected or [])})
        return {"profile_id": f"p{n}", "version": n, "rationale": f"idea {n}"}

    def new_run(self, ctx, wv, profile_ids, splits, repeats, purpose):
        return f"run:{splits[0]}:{'+'.join(profile_ids)}"

    def score(self, run_id, profile_id, splits):
        return (self.holdout if splits == ("holdout",) else self.practice)[profile_id]


def test_keeps_improvements_discards_regressions_and_proves_on_held_out_jobs(monkeypatch):
    loop = Loop(monkeypatch, practice={"p1": agg(0.5), "p2": agg(0.67), "p3": agg(0.5), "p4": agg(0.83)},
                holdout={"p1": agg(0.33, finished=3), "p4": agg(0.67, finished=3)})
    out = autofix.handle(loop.ctx)
    assert [r["accepted"] for r in out["rounds"]] == [True, False, True]
    assert out["best"]["profile_id"] == "p4" and out["original"]["profile_id"] == "p1"
    # round 2 built on the kept v2; round 3 still built on v2 (v3 was discarded) and was told what did not help
    assert [p["from"] for p in loop.proposals] == ["p1", "p2", "p2"]
    assert loop.proposals[2]["rejected"] == [{"rationale": "idea 3", "verified_rate": 0.5}]
    assert loop.runs[-1] == "run:holdout:p1+p4"  # the original and the best, side by side, on unseen jobs
    assert out["holdout"]["best"]["success_rate"] == 0.67 and out["holdout"]["original"]["success_rate"] == 0.33


def test_stops_early_when_every_practice_job_passes(monkeypatch):
    loop = Loop(monkeypatch, practice={"p1": agg(0.5), "p2": agg(1.0)}, holdout={"p1": agg(0.5), "p2": agg(1.0)})
    out = autofix.handle(loop.ctx)
    assert len(out["rounds"]) == 1 and out["best"]["profile_id"] == "p2" and len(loop.proposals) == 1


def test_no_held_out_rehearsal_when_nothing_beat_the_original(monkeypatch):
    loop = Loop(monkeypatch, practice={"p1": agg(0.5), "p2": agg(0.33), "p3": agg(0.5), "p4": agg(0.17)})
    out = autofix.handle(loop.ctx)
    assert out["best"]["profile_id"] == "p1" and out["holdout"] is None
    assert not any(r.startswith("run:holdout") for r in loop.runs)


def test_resumes_from_the_checkpoint_after_a_restart(monkeypatch):
    loop = Loop(monkeypatch, practice={"p1": agg(0.5), "p2": agg(0.67), "p3": agg(0.83), "p4": agg(0.9)},
                holdout={"p1": agg(0.5), "p4": agg(0.9)})
    real_rehearse = autofix._rehearse
    calls = {"n": 0}

    def crash_on_second(ctx, run_id):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("worker lost")
        loop.runs.append(run_id)

    monkeypatch.setattr(autofix, "_rehearse", crash_on_second)
    with pytest.raises(RuntimeError):
        autofix.handle(loop.ctx)
    saved = loop.ctx.checkpoint["autofix"]
    assert saved["phase"] == "rehearse" and saved["current"]["version"] == 3 and len(saved["rounds"]) == 1
    monkeypatch.setattr(autofix, "_rehearse", lambda ctx, run_id: loop.runs.append(run_id))
    out = autofix.handle(loop.ctx)  # a new attempt picks up round 2 instead of starting over
    assert [r["round"] for r in out["rounds"]] == [1, 2, 3] and len(loop.proposals) == 3
    assert real_rehearse is not None


def test_a_run_without_practice_episodes_is_refused(monkeypatch):
    loop = Loop(monkeypatch, practice={"p1": agg(None, finished=0)})
    with pytest.raises(ValueError, match="no finished train/dev episodes"):
        autofix.handle(loop.ctx)
