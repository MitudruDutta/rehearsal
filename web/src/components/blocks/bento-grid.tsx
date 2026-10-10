import { ArrowRight } from "lucide-react";
import type { ComponentPropsWithoutRef, ComponentType, ReactNode } from "react";
import { cn } from "@/lib/utils";

/* A bento grid after Magic UI's (magicui.design/docs/components/bento-grid), rebuilt as two zones per card: an
   illustration on a recessed stage, then the icon, title and description. The stage has one height and cards in
   a row stretch to match, so the stages, the dividing lines and the text all line up across a row. */

export function BentoGrid({ children, className, ...props }: ComponentPropsWithoutRef<"div"> & { children: ReactNode }) {
  return (
    <div className={cn("grid w-full grid-cols-1 gap-4 lg:grid-cols-3", className)} {...props}>
      {children}
    </div>
  );
}

export function BentoCard({
  name,
  description,
  Icon,
  visual,
  href,
  cta,
  className,
  ...props
}: ComponentPropsWithoutRef<"div"> & { name: string; description: string; Icon: ComponentType<{ className?: string }>; visual: ReactNode; href?: string; cta?: string }) {
  return (
    <div
      className={cn(
        "group relative flex flex-col overflow-hidden rounded-2xl border bg-card transition-colors duration-300 hover:border-primary/40",
        "shadow-[inset_0_1px_0_0_rgb(255_255_255/0.05),0_24px_48px_-32px_rgb(0_0_0/0.55)]",
        className,
      )}
      {...props}
    >
      {/* the stage: a faint dot grid, and a glow in the accent colour that warms when the card is hovered */}
      <div className="relative flex min-h-52 items-center overflow-hidden border-b bg-background/60 p-5 lg:h-52">
        <div className="pointer-events-none absolute inset-0 [background-image:radial-gradient(var(--border)_1px,transparent_1px)] [background-size:16px_16px] [mask-image:radial-gradient(ellipse_85%_85%_at_50%_45%,#000_30%,transparent_100%)]" />
        <div className="pointer-events-none absolute -top-28 left-1/2 h-48 w-2/3 -translate-x-1/2 rounded-full bg-primary/20 opacity-50 blur-3xl transition-opacity duration-500 group-hover:opacity-100" />
        <div className="relative w-full">{visual}</div>
      </div>
      <div className="flex flex-1 flex-col p-6">
        <div className="flex items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-primary/25 bg-primary/10 text-primary">
            <Icon className="size-[18px]" />
          </span>
          <h3 className="text-[17px] font-semibold leading-snug">{name}</h3>
        </div>
        <p className="mt-3 max-w-xl text-pretty text-sm leading-relaxed text-muted-foreground">{description}</p>
        {href && cta && (
          <a href={href} className="mt-4 inline-flex w-fit items-center gap-1.5 text-sm font-medium text-primary underline-offset-4 hover:underline">
            {cta} <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-0.5" />
          </a>
        )}
      </div>
    </div>
  );
}
