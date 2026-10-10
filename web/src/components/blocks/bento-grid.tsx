import { ArrowRight } from "lucide-react";
import type { ComponentPropsWithoutRef, ComponentType, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/* Adapted from Magic UI's Bento Grid (magicui.design/docs/components/bento-grid): theme tokens instead of
   fixed neutrals, lucide icons, and an optional call to action. */

export function BentoGrid({ children, className, ...props }: ComponentPropsWithoutRef<"div"> & { children: ReactNode }) {
  return (
    <div className={cn("grid w-full auto-rows-[20rem] grid-cols-1 gap-4 md:grid-cols-3", className)} {...props}>
      {children}
    </div>
  );
}

export function BentoCard({
  name,
  description,
  Icon,
  background,
  href,
  cta,
  className,
  ...props
}: ComponentPropsWithoutRef<"div"> & { name: string; description: string; Icon: ComponentType<{ className?: string }>; background: ReactNode; href?: string; cta?: string }) {
  return (
    <div
      className={cn(
        "group relative flex flex-col justify-end overflow-hidden rounded-xl border bg-card",
        "[box-shadow:0_1px_0_0_rgba(255,255,255,.04)_inset,0_12px_24px_rgba(0,0,0,.12)] dark:[box-shadow:0_-20px_80px_-20px_rgba(139,125,255,.12)_inset]",
        className,
      )}
      {...props}
    >
      <div className="absolute inset-0">{background}</div>
      <div className="pointer-events-none relative z-10 bg-gradient-to-t from-card via-card/95 to-transparent p-5 pt-12 transition-transform duration-300 lg:group-hover:-translate-y-6">
        <Icon className="size-7 text-primary transition-transform duration-300 group-hover:scale-90" />
        <h3 className="mt-2 text-lg font-semibold">{name}</h3>
        <p className="mt-1 max-w-lg text-sm text-muted-foreground">{description}</p>
      </div>
      {href && cta && (
        <div className="absolute bottom-0 z-20 hidden w-full translate-y-6 p-5 opacity-0 transition-all duration-300 group-hover:translate-y-0 group-hover:opacity-100 lg:flex">
          <Button variant="link" asChild size="sm" className="p-0">
            <a href={href}>{cta} <ArrowRight className="size-4" /></a>
          </Button>
        </div>
      )}
    </div>
  );
}
