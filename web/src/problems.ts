/** Plain-language explanations for failures. Raw provider and compiler errors stay in the server logs;
 * the console says what happened and what to do next. */

const RULES: [RegExp, string][] = [
  [/token that expires|invalid token|expired or otherwise invalid|token (is|has) expired|\b401\b[^.]{0,80}token/i, "The sign-in tokens saved for this world stopped working during the build, so the compiler could no longer use the application."],
  [/invalid 'parameters' schema|function has invalid/i, "The model provider rejected one of this world's tool definitions, so the agent never got a turn. This episode isn't counted against the agent."],
  [/billing|spend limit|payment method|insufficient[_ ](credit|quota)/i, "The model provider refused the request for billing reasons. Check the provider account, then run it again."],
  [/rate.?limit|\b429\b|too many requests/i, "The model provider is limiting requests right now. Try again in a few minutes."],
  [/model unavailable|all models in chain failed/i, "The model provider didn't answer, so the agent couldn't act. This episode isn't counted against the agent."],
  [/participant could not post/i, "The simulated customer couldn't post their message in the application, so the episode couldn't start properly."],
  [/oracle failed/i, "The checks couldn't read the application's database, so this episode couldn't be scored."],
  [/without an accepted submit_seed/i, "The compiler couldn't produce fictional data that replays cleanly."],
  [/without an accepted submit_runtime/i, "The compiler couldn't get the application to start in the sandbox."],
  [/same problem came back/i, "The compiler met the same problem several times at one step, so it stopped early instead of spending more."],
  [/without an accepted submit_(\w+)|output rejected \d+ times/i, "A compiler step ran out of attempts."],
  [/could not be started|BuildFailed/i, "The application didn't start in the sandbox after several repair attempts. Check that the images are complete and pinned."],
  [/lease expired|worker loss|claim lost|lease lost/i, "The worker running this job stopped."],
  [/budget/i, "The job reached its model-spend budget and stopped."],
  [/cancel|stop requested/i, "Stopped on request."],
  [/network .* not found|No such container|docker/i, "The sandbox was removed while the job was running."],
];

export function explainProblem(raw?: string | null): string {
  if (!raw) return "Something went wrong. The details are in the server log.";
  for (const [pattern, text] of RULES) if (pattern.test(raw)) return text;
  return "Something went wrong. The details are in the server log.";
}

/** What to do after a failed build. `restart` says whether Restart build can fix it. */
const NEXT: [RegExp, boolean, string][] = [
  [/token that expires|invalid token|expired or otherwise invalid|token (is|has) expired|\b401\b[^.]{0,80}token/i, false, "Restart build will not help: the cause is in an earlier step that is already saved. Use Build new version on the Applications page; it starts from the first step."],
  [/billing|spend limit|payment method|insufficient[_ ](credit|quota)/i, true, "Fix the provider account, then use Restart build. It continues from the last saved step."],
  [/rate.?limit|\b429\b|too many requests|model unavailable|all models in chain failed/i, true, "Wait a few minutes, then use Restart build. It continues from the last saved step."],
  [/budget/i, false, "Start a new build with a higher budget."],
  [/same problem came back/i, false, "Restart build is unlikely to help: it would meet the same problem. Use Build new version on the Applications page; it starts from the first step."],
  [/without an accepted submit_|output rejected \d+ times|could not be started|BuildFailed/i, true, "Use Restart build once; it continues from the last saved step. If it stops at the same step again, more restarts will not help: use Build new version on the Applications page."],
];

export function nextStep(raw?: string | null): { restart: boolean; text: string } {
  for (const [pattern, restart, text] of NEXT) if (raw && pattern.test(raw)) return { restart, text };
  return { restart: true, text: "Use Restart build. It continues from the last saved step; finished steps are not repeated." };
}

const ENDINGS: Record<string, string> = {
  environment_error: "not scored: setup problem",
  claimed_complete: "agent said it was done",
  stalled: "agent stopped acting",
  max_turns: "ran out of turns",
  goal_satisfied: "request satisfied",
};

export function describeEnding(termination?: string | null): string {
  return termination ? ENDINGS[termination] ?? termination.replace(/_/g, " ") : "running";
}

/** What a kind of compiler rejection means, for the build page's "why it is stuck". The kinds are Rehearsal's own
 * rejection messages, grouped by the server (rejection_kind). */
const REJECTIONS: [RegExp, string][] = [
  [/host check|DisallowedHost|ALLOWED_HOSTS|Invalid HTTP_HOST|Blocked host/i, "The application refuses requests addressed to its sandbox hostname. The build goes back to the runtime step to allow it."],
  [/not valid JSON/i, "The model wrote broken JSON, such as a bracket too many or too few. Common slips are repaired; the rest go back to the model."],
  [/example calls? did not succeed/i, "Tool example calls failed against the seeded data: usually the seed has no records for them to act on, or a field has the wrong shape for the application's API."],
  [/seed step .* failed/i, "A step that creates the fictional data failed when replayed from a clean start."],
  [/token that expires|login session/i, "A role signs in with a short-lived login token. A world is replayed for weeks, so each role needs a credential that lasts."],
  [/missing value/i, "A seed step saved a value from the wrong place in the response."],
  [/validation error/i, "The model's answer did not match the required format."],
  [/you submitted .* tools/i, "The tool list had too few or too many tools."],
  [/at least|got #/i, "The answer was incomplete: it had fewer items than the step requires."],
  [/sandbox start failed|could not be started/i, "The application did not start in the sandbox; the builder is repairing the runtime."],
];

export function explainRejection(kind: string): string {
  for (const [pattern, text] of REJECTIONS) if (pattern.test(kind)) return text;
  return "The model's answer was sent back with the reason shown.";
}
