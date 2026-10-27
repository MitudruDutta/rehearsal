"""Hand-written Gitea world used only to test the runner, gateway, engine, and
oracle. Published worlds come from the World Compiler, not from this file."""

from rehearsal.core.contracts import (
    ActorSpec, CheckSpec, CredentialSpec, EventAction, GoalVersion, HealthSpec, NegativeTrajectory,
    ParticipantSpec, RoleSpec, ScenarioSpec, ScheduledEvent, SeedStep, ServiceSpec, StateProbe,
    ToolParam, ToolSpec, TrajectoryStep, Trigger, WorldManifest,
)

IMAGE = "gitea/gitea:28.1.0@sha256:f505a0d3a41323b786e05942fc7a4075e07ae7c169fd9485649aa55ee543a21a"
P = "/api/v1/repos/{owner}/{repo}"


def _owner_repo():
    return [ToolParam(name="owner", location="path"), ToolParam(name="repo", location="path")]


def world() -> WorldManifest:
    return WorldManifest(
        name="gitea-fixture",
        services=[ServiceSpec(
            name="gitea", image=IMAGE, port=3000, data_paths=["/data"],
            env={"GITEA__database__DB_TYPE": "sqlite3", "GITEA__security__INSTALL_LOCK": "true",
                 "GITEA__server__ROOT_URL": "http://gitea:3000/"},
            health=HealthSpec(http_path="/api/healthz", timeout_s=180))],
        secrets=["admin_password", "agent_password"],
        state_probes=[StateProbe(kind="sqlite", service="gitea", path="/data/gitea/gitea.db")],
        seed=[
            SeedStep(kind="exec", service="gitea", user="git", command=["gitea", "admin", "user", "create", "--username", "triager", "--password", "{{secret.agent_password}}", "--email", "triager@example.test", "--must-change-password=false"]),
            SeedStep(kind="exec", service="gitea", user="git", command=["gitea", "admin", "user", "generate-access-token", "--username", "triager", "--token-name", "rehearsal", "--scopes", "all", "--raw"], save={"triager_token": "$stdout"}),
            SeedStep(service="gitea", method="POST", path="/api/v1/user/repos", headers={"Authorization": "token {{vars.triager_token}}"}, json_body={"name": "demo"}, save={"repo_id": "id"}),
        ],
        roles=[RoleSpec(name="triager", description="Maintainer who triages issues in the demo repository", customer_channel=True,
                        credential=CredentialSpec(template="token {{vars.triager_token}}"))],
        tools=[
            ToolSpec(name="list_issues", description="List issues of a repository", service="gitea", method="GET", path=P + "/issues",
                     params=[*_owner_repo(), ToolParam(name="state", location="query", required=False)], mutating=False, roles=["triager"]),
            ToolSpec(name="create_issue", description="Open an issue", service="gitea", method="POST", path=P + "/issues",
                     params=[*_owner_repo(), ToolParam(name="title", location="body"), ToolParam(name="body", location="body", required=False)], mutating=True, roles=["triager"]),
            ToolSpec(name="edit_issue", description="Edit an issue; set state to closed or open", service="gitea", method="PATCH", path=P + "/issues/{index}",
                     params=[*_owner_repo(), ToolParam(name="index", location="path", schema={"type": "integer"}), ToolParam(name="state", location="body", required=False)], mutating=True, roles=["triager"]),
            ToolSpec(name="comment_issue", description="Comment on an issue", service="gitea", method="POST", path=P + "/issues/{index}/comments",
                     params=[*_owner_repo(), ToolParam(name="index", location="path", schema={"type": "integer"}), ToolParam(name="body", location="body")], mutating=True, roles=["triager"]),
        ],
    )


def scenario() -> ScenarioSpec:
    args = {"owner": "triager", "repo": "demo"}
    return ScenarioSpec(
        id="file_then_close", title="File a bug, then close it when the customer says it is fixed", family="issue_lifecycle",
        actors=[ActorSpec(id="triager", role="triager", instructions="Handle the customer's requests about the triager/demo repository.", can_complete=True)],
        participant=ParticipantSpec(name="Ana", persona="A user of the demo project.", facts=["Login fails with error 500 since this morning."],
                                    opening_message="Please open an issue in triager/demo titled 'Login fails' describing error 500 on login."),
        goals=[GoalVersion(version=1, instruction="An issue titled 'Login fails' exists.", checks=["issue_exists"]),
               GoalVersion(version=2, instruction="It's fixed now: close the 'Login fails' issue and leave one comment saying it is resolved.", checks=["issue_exists", "issue_closed", "one_comment"])],
        constraints=["no_duplicate_issue"],
        checks=[
            CheckSpec(id="issue_exists", description="issue exists", query="SELECT count(*) >= 1 FROM issue WHERE repo_id = :repo_id AND name = 'Login fails'", value=1),
            CheckSpec(id="issue_closed", description="issue closed", query="SELECT count(*) FROM issue WHERE repo_id = :repo_id AND name = 'Login fails' AND is_closed = 1", value=1),
            CheckSpec(id="one_comment", description="exactly one comment", query="SELECT count(*) FROM comment c JOIN issue i ON i.id = c.issue_id WHERE i.repo_id = :repo_id AND c.type = 0", value=1),
            CheckSpec(id="no_duplicate_issue", description="no duplicate issue", query="SELECT count(*) FROM issue WHERE repo_id = :repo_id AND name = 'Login fails'", op="<=", value=1),
        ],
        events=[
            ScheduledEvent(id="drop_create", trigger=Trigger(kind="at_step", step=0), actions=[EventAction(kind="fault", tool="create_issue", fault_mode="drop_response")]),
            ScheduledEvent(id="fixed", trigger=Trigger(kind="after_tool", tool="list_issues"), actions=[EventAction(kind="goal_change", goal_version=2, text="Good news, it's fixed now. Please close that issue and add a comment saying it is resolved.")]),
        ],
        reference=[
            TrajectoryStep(actor="triager", tool="create_issue", args={**args, "title": "Login fails", "body": "Error 500 on login."}),
            TrajectoryStep(actor="triager", tool="list_issues", args={**args, "state": "all"}),
            TrajectoryStep(actor="triager", tool="edit_issue", args={**args, "index": 1, "state": "closed"}),
            TrajectoryStep(actor="triager", tool="comment_issue", args={**args, "index": 1, "body": "Resolved."}),
            TrajectoryStep(actor="triager", tool="complete", args={"summary": "closed"}),
        ],
        negatives=[
            NegativeTrajectory(name="blind_retry", description="retries the dropped create without checking", steps=[
                TrajectoryStep(actor="triager", tool="create_issue", args={**args, "title": "Login fails"}),
                TrajectoryStep(actor="triager", tool="create_issue", args={**args, "title": "Login fails"}),
                TrajectoryStep(actor="triager", tool="list_issues", args=args),
                TrajectoryStep(actor="triager", tool="edit_issue", args={**args, "index": 1, "state": "closed"}),
                TrajectoryStep(actor="triager", tool="comment_issue", args={**args, "index": 1, "body": "Resolved."}),
                TrajectoryStep(actor="triager", tool="complete", args={"summary": "done"})]),
            NegativeTrajectory(name="ignores_revision", description="never acts on goal v2", steps=[
                TrajectoryStep(actor="triager", tool="create_issue", args={**args, "title": "Login fails"}),
                TrajectoryStep(actor="triager", tool="list_issues", args=args),
                TrajectoryStep(actor="triager", tool="complete", args={"summary": "filed"})]),
        ],
        max_steps=20,
    )
