"use client";

import { Boxes, CircleCheck, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSeparator } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { GoogleButton } from "@/components/google-button";
import { api, post } from "../api";

/* Layout adapted from the shadcn/ui login-04 block: form on the left, product panel on the right. */

type Health = { signup: string; google_client_id: string | null };
type Mode = "signin" | "signup";

function ProductPanel() {
  const points = [
    { icon: Boxes, text: "Your real application, started from its own images in an isolated sandbox with fictional data" },
    { icon: CircleCheck, text: "Every outcome checked in the application's own database, never taken from the agent's word" },
    { icon: ShieldCheck, text: "No production access: nothing leaves the sandbox network" },
  ];
  return (
    <div className="relative hidden flex-col justify-between overflow-hidden bg-muted bg-[radial-gradient(ellipse_at_top_right,_color-mix(in_srgb,var(--primary)_28%,transparent),_transparent_60%)] p-8 md:flex">
      <div>
        <div className="flex items-center gap-2.5">
          <span className="size-3.5 rotate-45 rounded-[3px] bg-primary" aria-hidden="true" />
          <span className="font-heading text-lg font-bold">Rehearsal</span>
        </div>
        <p className="mt-6 font-heading text-2xl font-bold leading-tight">A dress rehearsal for your AI agent.</p>
      </div>
      <ul className="mt-10 space-y-4">
        {points.map((p) => (
          <li key={p.text} className="flex gap-3 text-sm text-muted-foreground">
            <p.icon className="mt-0.5 size-4 shrink-0 text-primary" />
            {p.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SignInForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/v1/auth/login", form);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit}>
      <FieldGroup className="gap-4">
        <Field>
          <FieldLabel htmlFor="email">Email</FieldLabel>
          <Input id="email" type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field>
          <FieldLabel htmlFor="password">Password</FieldLabel>
          <Input id="password" type="password" autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        <Button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</Button>
      </FieldGroup>
    </form>
  );
}

function SignUpForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/v1/auth/signup", form);
      onDone(); // the console continues with onboarding
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit}>
      <FieldGroup className="gap-4">
        <Field>
          <FieldLabel htmlFor="name">Full name</FieldLabel>
          <Input id="name" autoComplete="name" required value={form.name} onChange={set("name")} />
        </Field>
        <Field>
          <FieldLabel htmlFor="new-email">Work email</FieldLabel>
          <Input id="new-email" type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
        </Field>
        <Field>
          <FieldLabel htmlFor="new-password">Password</FieldLabel>
          <Input id="new-password" type="password" autoComplete="new-password" minLength={10} required value={form.password} onChange={set("password")} />
          <FieldDescription>At least 10 characters.</FieldDescription>
        </Field>
        {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
        <Button type="submit" disabled={busy}>{busy ? "Creating account…" : "Create account"}</Button>
      </FieldGroup>
    </form>
  );
}

export function Login({ onDone }: { onDone: () => void }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [mode, setMode] = useState<Mode>("signin");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Health>("/v1/health").then(setHealth).catch(() => setHealth({ signup: "closed", google_client_id: null }));
  }, []);
  const google = useCallback(
    async (credential: string) => {
      setError(null);
      try {
        await post("/v1/auth/google", { credential });
        onDone(); // new accounts continue with onboarding
      } catch (err) {
        setError((err as Error).message);
      }
    },
    [onDone],
  );
  const googleError = useCallback((m: string) => setError(m), []);
  if (!health) return null;
  const canSignUp = health.signup === "open";
  const signup = mode === "signup" && canSignUp;
  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted/40 p-6 md:p-10">
      <div className="w-full max-w-sm md:max-w-4xl">
        <Card className="overflow-hidden p-0">
          <CardContent className="grid p-0 md:grid-cols-2">
            <div className="flex min-w-0 flex-col justify-center p-6 md:p-10">
              <FieldGroup>
                <div className="flex flex-col gap-1">
                  <div className="mb-4 flex items-center gap-2.5 md:hidden">
                    <span className="size-3.5 rotate-45 rounded-[3px] bg-primary" aria-hidden="true" />
                    <span className="font-heading text-lg font-bold">Rehearsal</span>
                  </div>
                  <h1 className="text-2xl font-bold">{signup ? "Create your account" : "Welcome back"}</h1>
                  <p className="text-sm text-balance text-muted-foreground">
                    {signup ? "Set up your workspace in a minute, then build your first practice world." : "Sign in to your Rehearsal workspace."}
                  </p>
                </div>
                {health.google_client_id && (
                  <>
                    <Field>
                      <GoogleButton key={signup ? "up" : "in"} clientId={health.google_client_id} onCredential={google} onError={googleError} />
                    </Field>
                    <FieldSeparator className="*:data-[slot=field-separator-content]:bg-card">Or with email</FieldSeparator>
                  </>
                )}
                {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
                {signup ? <SignUpForm onDone={onDone} /> : <SignInForm onDone={onDone} />}
                {canSignUp && (
                  <FieldDescription className="text-center">
                    {signup ? "Already have an account? " : "New to Rehearsal? "}
                    <button type="button" className="underline underline-offset-4" onClick={() => { setError(null); setMode(signup ? "signin" : "signup"); }}>
                      {signup ? "Sign in" : "Create an account"}
                    </button>
                  </FieldDescription>
                )}
              </FieldGroup>
            </div>
            <ProductPanel />
          </CardContent>
        </Card>
        <p className="mt-4 px-6 text-center text-xs text-balance text-muted-foreground">
          Rehearsal keeps your name and email address to identify you in your workspace. API keys for the CLI and CI are created inside the console.
        </p>
      </div>
    </div>
  );
}
