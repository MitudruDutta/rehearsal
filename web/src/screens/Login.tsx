"use client";

import { ArrowRight, Check, CircleAlert, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { AuthShell } from "@/components/auth-shell";
import { GoogleButton } from "@/components/google-button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSeparator } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { api, post, sentence } from "../api";

/* Sign in and sign up are one screen in two modes. The landing page's "Start free" opens it with ?mode=signup;
   a server with sign-up closed shows sign-in only, and says why. */

type Health = { signup: string; google_client_id: string | null };
type Mode = "signin" | "signup";

const MIN_PASSWORD = 10; // the API refuses a shorter one

function Problem({ children }: { children: string }) {
  return (
    <Alert variant="destructive">
      <CircleAlert />
      <AlertDescription>{sentence(children)}</AlertDescription>
    </Alert>
  );
}

function PasswordInput({ id, value, onChange, autoComplete, minLength, describedBy }: { id: string; value: string; onChange: (value: string) => void; autoComplete: string; minLength?: number; describedBy?: string }) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input id={id} type={shown ? "text" : "password"} autoComplete={autoComplete} minLength={minLength} aria-describedby={describedBy} required value={value} onChange={(e) => onChange(e.target.value)} className="h-10 pr-10" />
      <button
        type="button"
        onClick={() => setShown(!shown)}
        aria-label={shown ? "Hide password" : "Show password"}
        aria-pressed={shown}
        className="absolute inset-y-0 right-0 grid w-10 place-items-center rounded-r-md text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
}

function Submit({ busy, label, busyLabel }: { busy: boolean; label: string; busyLabel: string }) {
  return (
    <Button type="submit" size="lg" disabled={busy} className="mt-1 w-full">
      {busy ? <LoaderCircle className="animate-spin" /> : null}
      {busy ? busyLabel : label}
      {busy ? null : <ArrowRight />}
    </Button>
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
          <Input id="email" type="email" autoComplete="email" autoCapitalize="none" spellCheck={false} autoFocus required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@company.com" className="h-10" />
        </Field>
        <Field>
          <FieldLabel htmlFor="password">Password</FieldLabel>
          <PasswordInput id="password" autoComplete="current-password" value={form.password} onChange={(password) => setForm({ ...form, password })} />
        </Field>
        {error && <Problem>{error}</Problem>}
        <Submit busy={busy} label="Sign in" busyLabel="Signing in…" />
      </FieldGroup>
    </form>
  );
}

function SignUpForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hint = useId();
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  const longEnough = form.password.length >= MIN_PASSWORD;
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
          <Input id="name" autoComplete="name" autoFocus required value={form.name} onChange={set("name")} className="h-10" />
        </Field>
        <Field>
          <FieldLabel htmlFor="new-email">Work email</FieldLabel>
          <Input id="new-email" type="email" autoComplete="email" autoCapitalize="none" spellCheck={false} required value={form.email} onChange={set("email")} placeholder="you@company.com" className="h-10" />
        </Field>
        <Field>
          <FieldLabel htmlFor="new-password">Password</FieldLabel>
          <PasswordInput id="new-password" autoComplete="new-password" minLength={MIN_PASSWORD} describedBy={hint} value={form.password} onChange={(password) => setForm({ ...form, password })} />
          <FieldDescription id={hint} className={cn("flex items-center gap-1.5", longEnough && "text-success")}>
            <Check className={cn("size-3.5", !longEnough && "opacity-40")} aria-hidden="true" />
            At least {MIN_PASSWORD} characters{form.password && !longEnough ? `: ${MIN_PASSWORD - form.password.length} more` : ""}
          </FieldDescription>
        </Field>
        {error && <Problem>{error}</Problem>}
        <Submit busy={busy} label="Create account" busyLabel="Creating account…" />
      </FieldGroup>
    </form>
  );
}

/** The mode the address asks for: "Start free" on the landing page leads to ?mode=signup. */
function modeFromAddress(): Mode {
  return typeof window !== "undefined" && new URLSearchParams(window.location.search).get("mode") === "signup" ? "signup" : "signin";
}

export function Login({ onDone }: { onDone: () => void }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [mode, setMode] = useState<Mode>(modeFromAddress);
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
  const canSignUp = health?.signup === "open";
  const signup = mode === "signup" && canSignUp;
  return (
    <AuthShell foot="Rehearsal keeps your name and email address to identify you in your workspace. API keys for the CLI and CI are created inside the console.">
      {!health ? (
        <div className="grid gap-4" aria-busy="true" aria-label="Loading">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-64" />
          <Skeleton className="mt-4 h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : (
        <FieldGroup className="gap-6">
          <div className="grid gap-1.5">
            <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight">{signup ? "Create your account" : "Welcome back"}</h1>
            <p className="text-[0.9375rem] text-muted-foreground">
              {signup ? "Set up your workspace in a minute, then build your first practice world." : "Sign in to your Rehearsal workspace."}
            </p>
          </div>
          {health.google_client_id && (
            <>
              <Field>
                <GoogleButton key={signup ? "up" : "in"} clientId={health.google_client_id} onCredential={google} onError={googleError} />
              </Field>
              <FieldSeparator>or with email</FieldSeparator>
            </>
          )}
          {error && <Problem>{error}</Problem>}
          {signup ? <SignUpForm onDone={onDone} /> : <SignInForm onDone={onDone} />}
          {canSignUp ? (
            <p className="text-center text-sm text-muted-foreground">
              {signup ? "Already have an account? " : "New to Rehearsal? "}
              <button type="button" className="font-medium text-foreground underline underline-offset-4 outline-none hover:text-primary focus-visible:text-primary" onClick={() => { setError(null); setMode(signup ? "signin" : "signup"); }}>
                {signup ? "Sign in" : "Create an account"}
              </button>
            </p>
          ) : (
            <p className="text-center text-sm text-muted-foreground">New accounts are closed on this server. Ask an owner of your organisation to add you.</p>
          )}
        </FieldGroup>
      )}
    </AuthShell>
  );
}
