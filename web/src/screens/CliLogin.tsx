"use client";

import { CheckCircle2, ShieldAlert, Terminal, XCircle } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, post, useResource } from "../api";

function when(iso?: string) {
  return iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";
}

/** Approve or deny a terminal that ran `rehearsal login`. */
export function CliLogin({ code }: { code: string }) {
  const info = useResource<any>(code ? `/v1/cli/logins/${encodeURIComponent(code)}` : null);
  const [result, setResult] = useState<"approved" | "denied" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const decide = async (decision: "approve" | "deny") => {
    setBusy(true);
    try {
      const r = await post(`/v1/cli/logins/${encodeURIComponent(code)}/${decision}`);
      setResult(r.status);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const d = info.data;
  return (
    <div className="mx-auto max-w-lg py-10">
      <Card>
        <CardHeader>
          <div className="mb-2 grid size-10 place-items-center rounded-lg bg-primary/15 text-primary"><Terminal className="size-5" /></div>
          <CardTitle>Sign in the Rehearsal CLI</CardTitle>
          <CardDescription>
            {result === "approved" ? "Done. Return to your terminal; it is signed in now." :
              result === "denied" ? "Denied. The terminal was not signed in." :
                "A terminal asked to sign in with your account. Approve it only if you just ran rehearsal login yourself."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!code && <p className="text-sm text-destructive">This link has no sign-in code. Run rehearsal login again and use the link it prints.</p>}
          {(info.error || error) && <p className="text-sm text-destructive">{error || info.error}</p>}
          {result === "approved" && <p className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="size-4" /> A new key with Build and evaluate access was created for this terminal. You can revoke it on the API keys page.</p>}
          {result === "denied" && <p className="flex items-center gap-2 text-sm text-muted-foreground"><XCircle className="size-4" /> Nothing was created.</p>}
          {d && !result && (
            <>
              <div className="rounded-lg border bg-muted/40 p-4 text-center">
                <div className="text-xs text-muted-foreground">Check that your terminal shows the same code</div>
                <div className="mt-1 font-mono text-3xl font-semibold tracking-[0.2em]">{d.user_code}</div>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
                <dt className="text-muted-foreground">Terminal</dt><dd className="font-medium">{d.client || "unnamed"}</dd>
                <dt className="text-muted-foreground">From address</dt><dd>{d.requested_ip || "unknown"}</dd>
                <dt className="text-muted-foreground">Requested at</dt><dd>{when(d.created_at)} (expires {when(d.expires_at)})</dd>
                <dt className="text-muted-foreground">Workspace</dt><dd>{d.workspace}, project {d.project}</dd>
                <dt className="text-muted-foreground">Access</dt><dd>Build and evaluate: add applications, build worlds, run evaluations, read results. Not keys or billing.</dd>
              </dl>
              {d.status !== "pending" && <p className="text-sm text-muted-foreground">This request is already {d.status}.</p>}
              {!d.can_approve && <p className="flex items-start gap-2 text-sm text-warning"><ShieldAlert className="mt-0.5 size-4 shrink-0" /> Only a workspace owner or admin can approve a terminal. Ask one, or create a key on the API keys page.</p>}
            </>
          )}
        </CardContent>
        {d && !result && d.status === "pending" && d.can_approve && (
          <CardFooter className="justify-end gap-2">
            <Button variant="outline" disabled={busy} onClick={() => decide("deny")}>Deny</Button>
            <Button disabled={busy} onClick={() => decide("approve")}>Approve</Button>
          </CardFooter>
        )}
      </Card>
    </div>
  );
}
