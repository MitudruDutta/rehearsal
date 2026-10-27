/* "Powered by": the services Rehearsal runs on, as a strip of logos that slides slowly and pauses under the pointer.
   Logos are the companies' own files (public/landing/partners/), grey until hovered; each opens the company's site.
   dodo-payments.svg is Dodo's logo with its lettering recoloured white, for this dark band. NVIDIA (Simple Icons, in NVIDIA
   green) and Nebius ship square marks, so those two show their name beside the mark.
   The list is drawn twice so the strip can loop without a gap; the second copy is hidden from screen readers. */

const PARTNERS: { name: string; href: string; src: string; height: number; label?: string }[] = [
  { name: "NVIDIA Nemotron", href: "https://www.nvidia.com/en-us/ai-data-science/foundation-models/nemotron/", src: "/landing/partners/nvidia.svg", height: 34, label: "NVIDIA Nemotron" },
  { name: "Nebius Token Factory", href: "https://nebius.com/token-factory", src: "/landing/partners/nebius.svg", height: 34, label: "Nebius Token Factory" },
  { name: "AWS", href: "https://aws.amazon.com/", src: "/landing/partners/aws.svg", height: 40 },
  { name: "Dodo Payments", href: "https://dodopayments.com/", src: "/landing/partners/dodo-payments.svg", height: 30 },
];

function Logos({ copy }: { copy?: boolean }) {
  return (
    <ul className="flex shrink-0 items-center" aria-hidden={copy || undefined}>
      {/* three passes of the list per copy, so one copy is wider than any screen */}
      {[0, 1, 2].flatMap((pass) =>
        PARTNERS.map((p) => (
          <li key={`${pass}-${p.name}`} className="px-10 md:px-14">
            <a
              href={p.href}
              target="_blank"
              rel="noopener noreferrer"
              tabIndex={copy || pass > 0 ? -1 : undefined}
              aria-label={copy || pass > 0 ? undefined : p.name}
              className="flex items-center gap-3 opacity-60 grayscale transition duration-300 hover:opacity-100 hover:grayscale-0 focus-visible:opacity-100 focus-visible:grayscale-0"
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- a static export, and SVGs need no resizing */}
              <img src={p.src} alt="" style={{ height: p.height }} className="w-auto max-w-none select-none" draggable={false} />
              {p.label && <span className="whitespace-nowrap font-heading text-xl font-semibold tracking-tight text-white">{p.label}</span>}
            </a>
          </li>
        )),
      )}
    </ul>
  );
}

export function PoweredBy() {
  return (
    // padding, not margin, above the band: a margin would escape this black section and show the page colour
    <div className="pt-16 md:pt-20">
    <section aria-label="Powered by" className="relative border-y border-white/10">
      <span className="absolute left-1/2 top-0 -translate-x-1/2 -translate-y-1/2 bg-black px-3 text-sm text-muted-foreground">Powered by</span>
      <div className="group overflow-hidden py-8 [mask-image:linear-gradient(90deg,transparent,#000_8%,#000_92%,transparent)]">
        <div className="flex w-max animate-[marquee_45s_linear_infinite] group-hover:[animation-play-state:paused] group-focus-within:[animation-play-state:paused]">
          <Logos />
          <Logos copy />
        </div>
      </div>
    </section>
    </div>
  );
}
