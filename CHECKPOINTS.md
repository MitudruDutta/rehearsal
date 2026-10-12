# How Rehearsal was built

Rehearsal was built with AI coding agents, and [Entire](https://entire.io) recorded the sessions. Each commit below carries an `Entire-Checkpoint` trailer: the checkpoint holds the agent session that produced it (prompts, reasoning, tool calls). Checkpoints are stored as git refs and pushed to a separate, private checkpoint repository. With access to it, `entire checkpoint explain <id>` shows one (a short id prefix works).

## Key decisions, in order

| When (IST) | Checkpoint | Decision |
|---|---|---|
| Oct 10, 14:52 | `01M4JHX2CY` | Record every agent session with Entire; run Entire's trail runners (risk, security, drift, review) on the repository |
| Oct 10, 15:01 | `01M4JJDKZ1` | Keep checkpoints in a private checkpoint repository, separate from the code |
| Oct 10, 14:56 | `01M4JJ5R7Y` | Run every evaluation job twice, with a stress layer on by default, so one lucky pass is not a result |
| Oct 10, 15:20 | `01M4JKGANJ` | The simulated customer repeats their request after changing it, so agents that act on the old request get caught |
| Oct 10, 15:36 | `01M4JMDMJV` | Model the business with cfo.ai (Ari) before setting prices |
| Oct 10, 15:52 | `01M4JNAXJC` | Adopt the adjusted pricing ("Option C") from the cfo.ai model: Free, Pro $29, Team $149, Enterprise |
| Oct 10, 16:18 | `01M4JPVJ6A` | Enforce plan limits in the API and take payments with Dodo Payments |
| Oct 10, 20:37 | `01M4K5MZSE` | Ship `rehearsal-kit` 0.1.1 on PyPI: agent plugin, `rehearsal login`, release gates |
| Oct 11, 00:52 | `01M4KM8EEC` | 0.1.2: browser sign-in for the CLI; a cloud database by default |
| Oct 11, 00:54 | `01M4KMD4QB` | Test that the package and every Dockerfile source exist, after a broken build reached main |
| Oct 11, 14:15 | `01M4N27BF9` | Let new users sign up on a shared browser; a free workspace starts with one sample application |
| Oct 11, 19:24 | `01M4ND4A6F` | Host production on AWS EC2 on Free-plan credits; the client defaults to rehearsalkit.xyz |
| Oct 11, 19:35 | `01M4NMH234` | Reach Supabase through its IPv4 session pooler, since EC2 has no IPv6 by default |
| Oct 11, 19:53 | `01M4NNH291` | Split the server: a small always-on web machine, and a worker machine that starts when a job is due and stops when idle |
| Oct 11, 20:44 | `01M4NRFT2S` | Serve the docs site's "Ask AI" from the web machine, answering only from the docs |
| Oct 11, 20:57 | `01M4NS7SH2` | Support the main model providers (OpenAI, Anthropic, Google, Groq, ...) with prices for every one, so spending caps always hold |
| Oct 12, 00:36 | `01M4P5Q7AT` | Say what the product proves: "prove your AI agent works before it ships" |
| Oct 12, 14:53 | `01M4QPRARD` | Fix the findings of a security review: image names can never become Docker options, image tags are unique per application, 1 MB body limit, security headers, Ask AI needs a known origin, the worker gets no payment or session secrets |

## Assessing a risky change with entire-graph

The security fix in `01M4QPRARD` changed how sandboxes start, so before shipping it we checked its blast radius with [entire-graph](https://docs.entire.io/guides/graph/overview), which builds a local code graph with no network access:

Output trimmed to the relevant lines:

```console
$ entire graph commit b286374          # what changed, entity by entity
rehearsal/runner/runtime.py (Python)
  ~ class WorldInstance body changed (47 dependents)
  ~ method WorldInstance._service_args body changed (4 dependents)
rehearsal/core/contracts.py (Python)
  + function image_ref added
  ~ class ServiceSpec body changed (23 dependents)
...

$ entire graph impact --symbol image_ref --exclude-tests
Blast radius: 7 callers (4 direct, 3 transitive), 0 callees, 0 type consumers, 2 data flows, 5 co-change files, 0 siblings.
Callers (4 direct, 3 transitive; who breaks if behavior changes):
- ApplicationIn._images (rehearsal/api/app.py:285, def :281)
- ServiceSpec._image (rehearsal/core/contracts.py:86, def :85)
- image_volumes (rehearsal/runner/runtime.py:93, def :92)
- WorldInstance._service_args (rehearsal/runner/runtime.py:287, def :272)
- inspect_image (rehearsal/runner/runtime.py:104, def :102) [via image_volumes]
- WorldInstance.create (rehearsal/runner/runtime.py:199, def :169) [via image_volumes]
- WorldInstance._start_services (rehearsal/runner/runtime.py:301, def :294) [+1 more call site, via WorldInstance._service_args]

$ entire graph impact --symbol world_key --exclude-tests
Blast radius: 11 callers (5 direct, 6 transitive), 1 callee, 0 type consumers, 0 data flows, 7 co-change files, 47 siblings.
(every caller is a Compiler method: _in_parallel, lane, instance, phase_materialize, and the phases that use them)
```

Every caller is on the path that starts a sandbox or accepts an application, which the new tests cover (`tests/unit/test_image_refs.py`). The image-tag key is read only by the World Compiler while it builds; evaluations start from a published manifest and snapshot, so existing worlds are not affected. Coding agents in this repository are told to use the graph before searching by hand (`.entire/graph-agent.md`).
