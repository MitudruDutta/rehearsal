"use client";

import { Bot, Boxes, GitCompareArrows, KeyRound, LayoutDashboard, LogOut, Moon, PlayCircle, Settings, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { Component, useEffect, useState, type ReactNode } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { api, ApiError } from "../../api";
import { go, RouterBridge, routes } from "../../nav";
import { Login } from "../../screens/Login";
import { Onboarding } from "../../screens/Onboarding";

class Boundary extends Component<{ children: ReactNode; route: string }, { error: string | null }> {
  state = { error: null as string | null };
  static getDerivedStateFromError(e: Error) {
    return { error: e.message };
  }
  componentDidUpdate(prev: { route: string }) {
    if (prev.route !== this.props.route && this.state.error) this.setState({ error: null });
  }
  render() {
    return this.state.error ? (
      <Alert variant="destructive">
        <AlertTitle>This view failed to render</AlertTitle>
        <AlertDescription>{this.state.error}. Reload the page, or open another section.</AlertDescription>
      </Alert>
    ) : (
      this.props.children
    );
  }
}

const NAV = [
  { href: routes.overview, label: "Overview", icon: LayoutDashboard, match: ["/app/"] },
  { href: routes.applications, label: "Applications", icon: Boxes, match: ["/app/applications/", "/app/build/", "/app/world/"] },
  { href: routes.agents, label: "Agents", icon: Bot, match: ["/app/agents/"] },
  { href: routes.runs(), label: "Runs", icon: PlayCircle, match: ["/app/runs/", "/app/run/"] },
  { href: routes.compare(), label: "Compare", icon: GitCompareArrows, match: ["/app/compare/"] },
  { href: routes.apiKeys, label: "API keys", icon: KeyRound, match: ["/app/api-keys/"] },
  { href: routes.settings, label: "Settings", icon: Settings, match: ["/app/settings/"] },
];

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme !== "light";
  return (
    <SidebarMenuButton onClick={() => setTheme(dark ? "light" : "dark")} tooltip="Switch theme">
      {dark ? <Sun /> : <Moon />}
      <span>{dark ? "Light mode" : "Dark mode"}</span>
    </SidebarMenuButton>
  );
}

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  const path = usePathname() || "/app/";
  const norm = path.endsWith("/") ? path : path + "/";
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [me, setMe] = useState<{ organization?: string; project?: string; needs_onboarding?: boolean; user?: { name: string; email: string; picture_url?: string } | null } | null>(null);
  useEffect(() => {
    if (authed === false) return;
    api<any>("/v1/me")
      .then((m) => {
        setMe(m);
        setAuthed(true);
      })
      .catch((e) => setAuthed(e instanceof ApiError && e.status === 401 ? false : true));
  }, [authed]);
  if (authed === null) return null;
  if (!authed) return <Login onDone={() => setAuthed(null)} />;
  if (me?.needs_onboarding)
    return (
      <Onboarding
        firstName={(me.user?.name || "").split(" ")[0]}
        onDone={(to) => {
          setAuthed(null); // reload /v1/me: the session now points at the new project
          if (to) go(to);
        }}
      />
    );
  const current = NAV.find((n) => n.match.includes(norm)) ?? NAV[0];
  const signOut = async () => {
    await api("/v1/session", { method: "DELETE" });
    location.reload();
  };
  return (
    <SidebarProvider>
      <RouterBridge />
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <Link href="/" className="flex items-center gap-2.5 px-2 py-1.5">
            <span className="size-3.5 shrink-0 rotate-45 rounded-[3px] bg-primary" aria-hidden="true" />
            <span className="font-heading text-lg font-bold group-data-[collapsible=icon]:hidden">Rehearsal</span>
          </Link>
          {me?.organization && (
            <div className="flex items-center gap-2.5 rounded-md border bg-sidebar-accent/40 p-2 group-data-[collapsible=icon]:hidden">
              <span className="grid size-8 shrink-0 place-items-center rounded-md bg-primary/15 text-sm font-semibold text-primary">{me.organization.slice(0, 1).toUpperCase()}</span>
              <span className="grid min-w-0 leading-tight">
                <span className="truncate text-sm font-medium">{me.organization}</span>
                <span className="truncate text-xs text-muted-foreground">Project: {me.project}</span>
              </span>
            </div>
          )}
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Rehearse</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {NAV.map((n) => (
                  <SidebarMenuItem key={n.label}>
                    <SidebarMenuButton asChild isActive={n === current} tooltip={n.label}>
                      <Link href={n.href}>
                        <n.icon />
                        <span>{n.label}</span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            {me?.user && (
              <SidebarMenuItem>
                <div className="flex items-center gap-2.5 px-2 py-1.5 group-data-[collapsible=icon]:px-0" title={me.user.email}>
                  <Avatar className="size-7 shrink-0">
                    {me.user.picture_url && <AvatarImage src={me.user.picture_url} alt="" referrerPolicy="no-referrer" />}
                    <AvatarFallback className="text-xs">{(me.user.name || me.user.email).slice(0, 1).toUpperCase()}</AvatarFallback>
                  </Avatar>
                  <span className="grid min-w-0 leading-tight group-data-[collapsible=icon]:hidden">
                    <span className="truncate text-sm font-medium">{me.user.name}</span>
                    <span className="truncate text-xs text-muted-foreground">{me.user.email}</span>
                  </span>
                </div>
              </SidebarMenuItem>
            )}
            <SidebarMenuItem><ThemeToggle /></SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton onClick={signOut} tooltip="Sign out"><LogOut /><span>Sign out</span></SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-background/85 px-4 backdrop-blur">
          <SidebarTrigger />
          <Separator orientation="vertical" className="mx-1 h-5" />
          <span className="text-sm font-medium text-muted-foreground">{current.label}</span>
          <div className="ml-auto">
            <Button asChild variant="ghost" size="sm"><Link href="/">About Rehearsal</Link></Button>
          </div>
        </header>
        <div className="mx-auto w-full max-w-[1500px] p-4 md:p-6">
          <Boundary route={path}>{children}</Boundary>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
