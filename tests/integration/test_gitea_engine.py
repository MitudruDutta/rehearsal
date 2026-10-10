"""Runner + gateway + engine + oracle against a real Gitea container (needs Docker)."""

import shutil
import tempfile
from pathlib import Path

import pytest

from rehearsal.agents.episode import Engine, MemoryRecorder, ScriptedPolicy
from rehearsal.runner.runtime import WorldInstance, new_secrets
from rehearsal.runner.seed import run_seed
from tests.fixtures.gitea_world import scenario, world

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker required")


@pytest.fixture(scope="module")
def instance():
    w = world()
    inst = WorldInstance.create(w, secrets=new_secrets(w.secrets))
    variables = run_seed(inst, w.seed, {})
    snap = Path(tempfile.mkdtemp(prefix="rh-test-snap-"))
    inst.snapshot(snap)
    yield inst, w, variables, snap
    inst.destroy()
    shutil.rmtree(snap, ignore_errors=True)


def _run(inst, w, variables, snap, steps):
    inst.restore(snap)
    rec = MemoryRecorder()
    eng = Engine(episode_id="ep_test0000000", instance=inst, manifest=w, scenario=scenario(), variables=dict(variables),
                 recorder=rec, policy=ScriptedPolicy(steps), participant_mode="scripted")
    return eng.run(), rec


def test_reference_passes_with_recovery(instance):
    inst, w, variables, snap = instance
    result, rec = _run(inst, w, variables, snap, scenario().reference)
    assert result.goal_version == 2
    assert result.goal_satisfied, result.check_results
    assert result.hard_constraint_violations == []
    assert result.recovery_result == "recovered"
    first = rec.actions[0]
    assert first["status"] == "UNKNOWN" and first["fault"] == "drop_response"
    assert first["response"]["status"] == 201  # the effect happened; the agent was not told
    assert "body" not in first["visible_result"]


@pytest.mark.parametrize("name", ["blind_retry", "ignores_revision"])
def test_negatives_fail(instance, name):
    inst, w, variables, snap = instance
    neg = next(n for n in scenario().negatives if n.name == name)
    result, _ = _run(inst, w, variables, snap, neg.steps)
    assert result.reward <= 0
    if name == "blind_retry":
        assert result.hard_constraint_violations == ["no_duplicate_issue"]
    else:
        assert not result.goal_satisfied and result.false_completion


def test_role_rejection(instance):
    inst, w, variables, snap = instance
    from rehearsal.runner.gateway import Gateway
    gw = Gateway(inst, w, variables)
    res = gw.execute("nobody", "create_issue", {"owner": "triager", "repo": "demo", "title": "x"}, "op_x")
    assert res.status == "REJECTED"
    res = gw.execute("triager", "create_issue", {"owner": "triager", "repo": "demo", "bogus": 1}, "op_y")
    assert res.status == "REJECTED" and "unknown arguments" in res.visible["error"]
