import Link from "next/link";

/** The console's mark (a blue tile with a white diamond) and name, followed by "Docs". Links to the docs home. */
export function Logo({ className = "" }: { className?: string }) {
  return (
    <Link href="/" aria-label="Rehearsal documentation home" className={`flex shrink-0 items-center gap-2.5 rounded-md ${className}`}>
      <span
        aria-hidden="true"
        className="grid size-7 place-items-center rounded-lg bg-[linear-gradient(180deg,#b7cbff_0%,#86a6ff_24%,#3a66e8_25%,#2446b8_100%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.5)]"
      >
        <span className="size-2 rotate-45 rounded-[2px] bg-white" />
      </span>
      <span className="font-heading text-[17px] font-bold tracking-tight text-foreground">Rehearsal</span>
      <span className="rounded-md border px-1.5 py-px text-xs font-medium text-muted-foreground">Docs</span>
    </Link>
  );
}
