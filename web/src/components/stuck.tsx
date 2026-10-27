"use client";

import { Pause } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { explainRejection } from "../problems";

type Kind = { count: number; role?: string; last?: string };

// a step whose top rejection has come back this often gets the warning; the server pauses the build at GUARD_REPEATS (10)
const WARN_AT = 3;

/** What keeps going wrong in the build's current step, grouped by kind, with a warning and Pause when it repeats. */
export function Stuck({ stuck, phase, status, guard, onPause }: {
  stuck?: Record<string, Record<string, Kind>>; phase?: string; status?: string; guard?: string | null; onPause: () => void;
}) {
  const step = phase && stuck?.[phase] ? phase : Object.keys(stuck || {}).at(-1);
  const kinds = Object.entries((step && stuck?.[step]) || {}).sort(([, a], [, b]) => b.count - a.count);
  if (!kinds.length) return null;
  const [topKind, top] = kinds[0];
  const total = kinds.reduce((n, [, k]) => n + k.count, 0);
  return (
    <>
      {status === "paused" && guard ? (
        <Alert className="mb-4 border-warning/50">
          <AlertTitle>Paused to save money</AlertTitle>
          <AlertDescription>{guard} Resume gives the step another round; if the cause below cannot change, stop the build instead.</AlertDescription>
        </Alert>
      ) : status === "running" && top.count >= WARN_AT ? (
        <Alert className="mb-4 border-warning/50">
          <AlertTitle>The {step} step keeps failing on the same cause</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{explainRejection(topKind)} It has come back {top.count} times. Each try spends model money.</span>
            <Button size="sm" variant="outline" onClick={onPause}><Pause /> Pause the build</Button>
          </AlertDescription>
        </Alert>
      ) : null}
      <Card className="mb-4">
        <CardHeader>
          <CardTitle>Why the {step} step is not finished</CardTitle>
          <CardDescription>{total} rejections of {kinds.length} kind{kinds.length === 1 ? "" : "s"}, over every attempt of this step. Each was sent back to the model with its reason.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="divide-y">
            {kinds.map(([kind, k]) => (
              <li key={kind} className="py-3 first:pt-0 last:pb-0">
                <div className="flex items-baseline justify-between gap-4">
                  <span className="font-medium">{explainRejection(kind)}</span>
                  <span className="shrink-0 tabular-nums text-sm text-muted-foreground">{k.count}×{k.role ? `, ${k.role}` : ""}</span>
                </div>
                {k.last && (
                  <details className="mt-1 text-sm text-muted-foreground">
                    <summary className="cursor-pointer">Latest reason</summary>
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-3 font-mono text-xs">{k.last}</pre>
                  </details>
                )}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </>
  );
}
