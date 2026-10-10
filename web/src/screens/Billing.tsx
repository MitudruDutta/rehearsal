"use client";

import { CreditCard, ExternalLink, Moon, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader, Tone } from "@/components/rh";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { post, useResource } from "../api";
import { useQuery } from "../nav";

const PRICES: Record<string, { month: number; year: number; blurb: string }> = {
  pro: { month: 29, year: 290, blurb: "3 applications, 2 world builds and 750 episodes a month, 2 sandboxes" },
  team: { month: 149, year: 1490, blurb: "20 applications, 8 world builds and 3,000 episodes a month, 4 sandboxes" },
};
const STATUS: Record<string, string> = { active: "Active", past_due: "Payment failed: retrying", on_hold: "On hold: payment failed", cancelled: "Cancelled", expired: "Ended", paused: "Paused", pending: "Starting" };

function day(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
}

function Meter({ label, used, limit, note }: { label: string; used: number; limit: number | null; note?: string }) {
  const share = limit ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular-nums text-muted-foreground">{limit === null ? `${used} used, no limit` : `${used} of ${limit}`}</span>
      </div>
      {limit !== null && <Progress value={share} className="h-1.5" aria-label={`${label}: ${used} of ${limit}`} />}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

/** The plan someone picked on the pricing page, one click from payment. It never pays or switches by itself. */
function Chosen({ item, d, busy, onBuy }: { item: string; d: any; busy: boolean; onBuy: () => void }) {
  const [name, period] = item.split("_");
  const p = PRICES[name];
  if (!p || !["monthly", "yearly"].includes(period)) return null;
  const interval = period === "monthly" ? "month" : "year";
  const sub = d.subscription;
  const current = !!sub?.paid && sub.plan === name && sub.interval === interval;
  const managed = d.plan.name === "internal" || d.plan.name === "enterprise";
  const ready = d.billing_enabled && d.items.includes(item) && !current && !managed;
  return (
    <Card className="mb-4 border-primary/50 bg-primary/5">
      <CardContent className="flex flex-wrap items-center justify-between gap-4 pt-6">
        <div>
          <div className="font-semibold">{name[0].toUpperCase() + name.slice(1)} plan, billed {period}: ${interval === "month" ? p.month : p.year} a {interval}</div>
          <p className="mt-1 text-sm text-muted-foreground">
            {current ? "This is already your plan." : managed ? "An operator manages this workspace's plan." : !d.billing_enabled ? "Payments are not set up on this server yet." : `${p.blurb}. You pay on Dodo Payments' secure page and can cancel at any time.`}
          </p>
        </div>
        {ready && <Button onClick={onBuy} disabled={busy}><CreditCard /> {sub?.paid ? `Switch to ${name}` : "Continue to payment"}</Button>}
      </CardContent>
    </Card>
  );
}

export function Billing() {
  const b = useResource<any>("/v1/billing");
  const back = useQuery("checkout");
  const buy = useQuery("buy"); // a plan chosen on the pricing page, e.g. pro_monthly
  const [interval, setInterval] = useState<"month" | "year">("month");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (back !== "done") return;
    post("/v1/billing/sync").then(() => { b.reload(); toast.success("Payment received. Your plan is up to date."); }).catch((e) => toast.error((e as Error).message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [back]);

  const act = async (key: string, fn: () => Promise<any>) => {
    setBusy(key);
    try {
      await fn();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  };
  const checkout = (item: string) => act(item, async () => { window.location.assign((await post("/v1/billing/checkout", { item })).url); });
  const change = (item: string) => act(item, async () => {
    await post("/v1/billing/change", { item });
    toast.success("Switching plans. The new plan applies when Dodo Payments confirms the charge, usually within a minute.");
    setTimeout(() => post("/v1/billing/sync").then(b.reload).catch(() => b.reload()), 45000);
  });
  const portal = () => act("portal", async () => { window.location.assign((await post("/v1/billing/portal")).url); });
  const sync = () => act("sync", async () => { await post("/v1/billing/sync"); b.reload(); toast.success("Checked with Dodo Payments."); });

  const d = b.data;
  if (!d) return <PageHeader title="Plan and billing" description={b.error || "Loading..."} />;
  const plan = d.plan, u = d.usage, sub = d.subscription;
  const subscribed = !!sub?.paid;
  const canBuy = (item: string) => d.billing_enabled && d.items.includes(item);
  const builds = plan.builds === null ? null : plan.builds + u.extra_builds;
  const episodes = plan.episodes === null ? null : plan.episodes + u.extra_episodes;

  return (
    <>
      <PageHeader
        title="Plan and billing"
        description="What your workspace can run, what it has used this month, and how to get more. Payments go through Dodo Payments."
        actions={sub && d.billing_enabled ? (
          <>
            <Button variant="outline" onClick={sync} disabled={busy === "sync"}><RefreshCw /> Check payment status</Button>
            <Button variant="outline" onClick={portal} disabled={busy === "portal"}><ExternalLink /> Invoices and payment method</Button>
          </>
        ) : undefined}
      />
      {buy && <Chosen item={buy} d={d} busy={busy === buy} onBuy={() => (subscribed ? change(buy) : checkout(buy))} />}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">{plan.title} plan {sub && <Tone tone={subscribed ? "go" : "stop"}>{STATUS[sub.status] ?? sub.status}</Tone>}</CardTitle>
              <CardDescription>
                {d.override ? "An operator set this plan for your workspace. " : ""}
                {sub?.period_end && subscribed ? (sub.cancel_at_period_end ? `Ends on ${day(sub.period_end)}; then the workspace moves to the free plan.` : `Renews on ${day(sub.period_end)}, billed ${sub.interval === "year" ? "yearly" : "monthly"}.`) : ""}
                {sub && !subscribed ? " Paid features are paused. Update the payment method to get them back." : ""}
                {` Monthly amounts start again on ${day(d.renews)}.`}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <Meter label="Applications" used={u.applications} limit={plan.applications} note="Removing an application frees its place." />
              <Meter label={plan.builds_ever ? "World builds (for good)" : "World builds this month"} used={u.builds} limit={builds}
                note={`${u.extra_builds ? `Includes ${u.extra_builds} from top-ups. ` : ""}A failed build can be restarted from its page without using another.${plan.build_budget_usd ? ` Each build stops at $${plan.build_budget_usd} of model use.` : ""}`} />
              <Meter label="Episodes this month" used={u.episodes} limit={episodes} note={`${u.extra_episodes ? `Includes ${u.extra_episodes.toLocaleString()} from top-ups. ` : ""}Episodes of a stopped run that never started are not counted.`} />
              <Meter label="Sandboxes in use" used={u.sandboxes} limit={plan.sandboxes} note="Each sandbox runs one part of an evaluation at a time." />
              {d.quiet_hours_utc && (
                <div className="flex gap-3 rounded-lg border bg-muted/40 p-3 text-sm">
                  <Moon className="mt-0.5 size-4 shrink-0 text-info" />
                  <p>On the free plan, evaluations start in quiet hours, {d.quiet_hours_utc} UTC{d.next_quiet_start ? `; the next window opens ${new Date(d.next_quiet_start).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" })} your time` : ", which is now"}. World builds start at once. Paid plans run everything at once.</p>
                </div>
              )}
            </CardContent>
          </Card>

          {plan.name !== "internal" && plan.name !== "enterprise" && (
            <Card>
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>Plans</CardTitle>
                  <CardDescription>{subscribed ? "Switching takes effect now; you pay or get credit for the difference." : "Cancel at any time from the payment portal."}</CardDescription>
                </div>
                <Tabs value={interval} onValueChange={(v) => setInterval(v as "month" | "year")}>
                  <TabsList><TabsTrigger value="month">Monthly</TabsTrigger><TabsTrigger value="year">Yearly: 2 months free</TabsTrigger></TabsList>
                </Tabs>
              </CardHeader>
              <CardContent className="grid gap-3 md:grid-cols-2">
                {Object.entries(PRICES).map(([name, p]) => {
                  const item = `${name}_${interval === "month" ? "monthly" : "yearly"}`;
                  const current = subscribed && sub.plan === name && sub.interval === interval;
                  return (
                    <div key={name} className={`rounded-lg border p-4 ${current ? "border-primary/60 bg-primary/5" : ""}`}>
                      <div className="flex items-baseline justify-between gap-2">
                        <h3 className="font-semibold capitalize">{name}</h3>
                        <span><span className="font-heading text-2xl font-bold">${interval === "month" ? p.month : p.year}</span> <span className="text-sm text-muted-foreground">/ {interval}</span></span>
                      </div>
                      <p className="mt-2 text-sm text-muted-foreground">{p.blurb}.</p>
                      <Button className="mt-4 w-full" variant={current ? "outline" : "default"} disabled={current || !canBuy(item) || busy === item}
                        onClick={() => (subscribed ? change(item) : checkout(item))}>
                        <CreditCard /> {current ? "Your plan" : subscribed ? `Switch to ${name}` : `Choose ${name}`}
                      </Button>
                    </div>
                  );
                })}
                {!d.billing_enabled && <p className="text-sm text-muted-foreground md:col-span-2">Payments are not set up on this server yet.</p>}
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Top-ups</CardTitle>
              <CardDescription>Add to this month when you run out. Top-ups end with the month and never renew by themselves.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {[
                { item: "episodes_1000", title: "1,000 episodes", price: "$30" },
                { item: "build_1", title: "1 world build", price: "$15" },
              ].map((t) => (
                <div key={t.item} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                  <div><div className="font-medium">{t.title}</div><div className="text-sm text-muted-foreground">{t.price}</div></div>
                  <Button variant="outline" size="sm" disabled={!plan.top_ups || !canBuy(t.item) || busy === t.item} onClick={() => checkout(t.item)}>Add</Button>
                </div>
              ))}
              {!plan.top_ups && <p className="text-xs text-muted-foreground">Top-ups are for paid plans.</p>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Enterprise</CardTitle></CardHeader>
            <CardContent className="text-sm text-muted-foreground">A runner inside your own cloud account, single sign-on, and custom limits, from $3,000 a month. Contact us to set it up.</CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
