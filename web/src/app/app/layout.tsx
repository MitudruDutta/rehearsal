"use client";

import { Bot, Boxes, ChevronsUpDown, GitCompareArrows, LayoutDashboard, LogOut, Moon, PanelLeftClose, PanelLeftOpen, PlayCircle, Settings, Sun, Terminal, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { DropdownMenu } from "radix-ui";
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
  useSidebar,
} from "@/components/ui/sidebar";
import { api, ApiError } from "../../api";
import { go, RouterBridge, routes } from "../../nav";
import { Login } from "../../screens/Login";
import { Onboarding } from "../../screens/Onboarding";
import { signOut } from "../../screens/Settings";
import { cn } from "@/lib/utils";

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
];

type Me = { organization?: string; project?: string; needs_onboarding?: boolean; is_admin?: boolean; plan?: string | null; user?: { name: string; email: string; picture_url?: string } | null };

/** Settings live in their own section (opened from the gear at the bottom of the sidebar), grouped by what they
 * apply to, so the sidebar holds only the pages you work in. URLs predate the section and stay as they are. */
function settingsGroups(me: Me | null) {
  return [
    { label: "Account", items: [{ href: routes.settings, label: "Profile" }, { href: routes.settingsAgents, label: "Coding agents" }] },
    ...(me?.plan ? [{ label: "Workspace", detail: me.organization, items: [{ href: routes.billing, label: "Billing" }] }] : []),
    {
      label: "Project",
      detail: me?.project,
      items: [
        { href: routes.apiKeys, label: "API keys" },
        { href: routes.settingsCredentials, label: "Credentials" },
        { href: routes.settingsExports, label: "Exports" },
      ],
    },
    ...(me?.is_admin ? [{ label: "Operator", items: [{ href: routes.admin, label: "Admin" }] }] : []),
  ];
}

function SettingsNav({ groups, path }: { groups: ReturnType<typeof settingsGroups>; path: string }) {
  return (
    <nav aria-label="Settings" className="-mx-4 flex gap-6 overflow-x-auto px-4 pb-2 md:mx-0 md:block md:space-y-5 md:overflow-visible md:px-0">
      <div className="hidden px-2 text-sm font-semibold md:block">Settings</div>
      {groups.map((g) => (
        <div key={g.label} className="shrink-0">
          <div className="truncate px-2 pb-1 text-xs text-muted-foreground">
            {g.label}
            {g.detail && <span className="opacity-70"> · {g.detail}</span>}
          </div>
          <ul className="flex gap-1 md:block md:space-y-0.5">
            {g.items.map((i) => (
              <li key={i.href}>
                <Link href={i.href} aria-current={i.href === path ? "page" : undefined} className={cn("block whitespace-nowrap rounded-md px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground", i.href === path && "bg-accent font-medium text-foreground")}>
                  {i.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** The sidebar opens and closes from its own top row (Ctrl+B too). Collapsed to icons, the logo becomes the expand button. */
function SidebarBrand() {
  const { state, isMobile, toggleSidebar } = useSidebar();
  if (state === "collapsed" && !isMobile)
    return (
      <button type="button" onClick={toggleSidebar} aria-label="Expand sidebar" title="Expand sidebar (Ctrl+B)" className="group/brand grid size-8 place-items-center rounded-md outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring">
        <span className="size-3.5 rotate-45 rounded-[3px] bg-primary group-hover/brand:hidden group-focus-visible/brand:hidden" aria-hidden="true" />
        <PanelLeftOpen className="hidden size-4 group-hover/brand:block group-focus-visible/brand:block" />
      </button>
    );
  const label = isMobile ? "Close sidebar" : "Collapse sidebar (Ctrl+B)";
  return (
    <div className="flex items-center gap-1">
      <Link href="/" className="flex min-w-0 flex-1 items-center gap-2.5 px-2 py-1.5">
        <span className="size-3.5 shrink-0 rotate-45 rounded-[3px] bg-primary" aria-hidden="true" />
        <span className="font-heading text-lg font-bold">Rehearsal</span>
      </Link>
      <Button variant="ghost" size="icon-sm" onClick={toggleSidebar} aria-label={label} title={label} className="text-muted-foreground">
        <PanelLeftClose />
      </Button>
    </div>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme !== "light";
  return (
    <Button variant="ghost" size="icon-sm" onClick={() => setTheme(dark ? "light" : "dark")} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} title={dark ? "Light mode" : "Dark mode"}>
      {dark ? <Sun /> : <Moon />}
    </Button>
  );
}

const MENU_ITEM = "flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none select-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground [&_svg]:size-4 [&_svg]:text-muted-foreground";

function AccountMenu({ me }: { me: Me | null }) {
  const name = me?.user?.name || me?.organization || "Account";
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button type="button" className="flex min-w-0 flex-1 items-center gap-2 rounded-md p-1.5 text-left outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-sidebar-ring group-data-[collapsible=icon]:flex-none" aria-label="Account menu">
          <Avatar className="size-6 shrink-0">
            {me?.user?.picture_url && <AvatarImage src={me.user.picture_url} alt="" referrerPolicy="no-referrer" />}
            <AvatarFallback className="text-xs">{name.slice(0, 1).toUpperCase()}</AvatarFallback>
          </Avatar>
          <span className="truncate text-sm font-medium group-data-[collapsible=icon]:hidden">{name}</span>
          <ChevronsUpDown className="ml-auto size-4 shrink-0 opacity-60 group-data-[collapsible=icon]:hidden" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content side="top" align="start" sideOffset={6} className="z-50 w-64 rounded-lg border bg-popover p-1 text-popover-foreground shadow-md">
          <div className="px-2 py-1.5">
            <div className="truncate text-sm font-medium">{name}</div>
            {me?.user?.email && <div className="truncate text-xs text-muted-foreground">{me.user.email}</div>}
          </div>
          <DropdownMenu.Separator className="-mx-1 my-1 h-px bg-border" />
          <DropdownMenu.Item asChild className={MENU_ITEM}><Link href={routes.settings}><UserRound /> Profile</Link></DropdownMenu.Item>
          <DropdownMenu.Item asChild className={MENU_ITEM}><Link href={routes.settingsAgents}><Terminal /> Coding agents</Link></DropdownMenu.Item>
          <DropdownMenu.Separator className="-mx-1 my-1 h-px bg-border" />
          <DropdownMenu.Item className={MENU_ITEM} onSelect={signOut}><LogOut /> Sign out</DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  const path = usePathname() || "/app/";
  const norm = path.endsWith("/") ? path : path + "/";
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [me, setMe] = useState<Me | null>(null);
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
  const groups = settingsGroups(me);
  const inSettings = groups.some((g) => g.items.some((i) => i.href === norm));
  const current = NAV.find((n) => n.match.includes(norm)) ?? (inSettings || norm === "/app/cli-login/" ? null : NAV[0]);
  const title = current?.label ?? (inSettings ? "Settings" : "CLI sign-in");
  return (
    <SidebarProvider>
      <RouterBridge />
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarBrand />
          {me?.organization && (
            <div className="flex items-center gap-2.5 rounded-md border bg-sidebar-accent/40 p-2 group-data-[collapsible=icon]:hidden">
              <span className="grid size-8 shrink-0 place-items-center rounded-md bg-primary/15 text-sm font-semibold text-primary">{me.organization.slice(0, 1).toUpperCase()}</span>
              <span className="grid min-w-0 leading-tight">
                <span className="truncate text-sm font-medium">{me.organization}</span>
                <span className="truncate text-xs text-muted-foreground">Project: {me.project}{me.plan ? `, ${me.plan} plan` : ""}</span>
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
          <div className="flex items-center gap-1 border-t pt-2 group-data-[collapsible=icon]:flex-col">
            <AccountMenu me={me} />
            <Button asChild variant="ghost" size="icon-sm" className={cn(inSettings && "bg-sidebar-accent text-sidebar-accent-foreground")}>
              <Link href={routes.settings} aria-label="Settings" title="Settings" aria-current={inSettings ? "page" : undefined}><Settings /></Link>
            </Button>
            <ThemeToggle />
          </div>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-background/85 px-4 backdrop-blur">
          <SidebarTrigger className="md:hidden" />
          <Separator orientation="vertical" className="mx-1 h-5 md:hidden" />
          <span className="text-sm font-medium text-muted-foreground">{title}</span>
          <div className="ml-auto">
            <Button asChild variant="ghost" size="sm"><Link href="/">About Rehearsal</Link></Button>
          </div>
        </header>
        <div className="mx-auto w-full max-w-[1500px] p-4 md:p-6">
          {inSettings ? (
            <div className="mx-auto grid max-w-6xl gap-6 md:grid-cols-[200px_minmax(0,1fr)] md:gap-10">
              <SettingsNav groups={groups} path={norm} />
              <div className="min-w-0"><Boundary route={path}>{children}</Boundary></div>
            </div>
          ) : (
            <Boundary route={path}>{children}</Boundary>
          )}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
