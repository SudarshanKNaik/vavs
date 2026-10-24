import Link from "next/link";

export function CtaSection() {
  return (
    <section className="bg-[#2C2420] py-28 md:py-40 relative overflow-hidden">
      {/* Subtle background texture */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
          backgroundRepeat: "repeat",
          backgroundSize: "200px",
        }}
        aria-hidden="true"
      />

      <div className="relative mx-auto max-w-7xl px-8">
        {/* Label */}
        <div className="flex items-center gap-4 mb-12">
          <span className="h-px w-8 bg-[#8C7B70]" />
          <p className="text-[11px] tracking-[0.22em] uppercase text-[#8C7B70]">
            Get Started
          </p>
        </div>

        <div className="grid gap-16 lg:grid-cols-[1fr_auto] lg:items-end">
          {/* Headline */}
          <h2 className="font-serif text-[clamp(2.8rem,6vw,5.5rem)] leading-[1.0] tracking-tight text-[#FAF8F5]">
            Stop chasing patients.
            <br />
            <em className="italic text-[#8C7B70]">Let the system do it.</em>
          </h2>

          {/* Action block */}
          <div className="flex flex-col gap-5 lg:items-end lg:pb-2">
            <p className="max-w-xs text-[14px] leading-[1.75] text-[#8C7B70] lg:text-right">
              Set up your first trigger in under 5 minutes. No integration fees,
              no long contracts.
            </p>
            <div className="flex items-center gap-4">
              <Link
                href="/signIn"
                className="inline-flex items-center gap-3 border border-[#FAF8F5] px-7 py-3.5 text-[13px] tracking-[0.08em] uppercase text-[#FAF8F5] transition-all duration-300 hover:bg-[#FAF8F5] hover:text-[#2C2420]"
              >
                Start Free
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 16 16"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path d="M2 8h12M9 3l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </Link>
              <Link
                href="/contact"
                className="text-[13px] tracking-[0.08em] uppercase text-[#8C7B70] hover:text-[#FAF8F5] transition-colors duration-300"
              >
                Talk to us
              </Link>
            </div>
          </div>
        </div>

        {/* Bottom rule with tagline */}
        <div className="mt-20 flex items-center justify-between border-t border-[#3D3028] pt-8">
          <p className="text-[11px] tracking-[0.15em] uppercase text-[#8C7B70]">
            HIPAA-ready infrastructure
          </p>
          <p className="text-[11px] tracking-[0.15em] uppercase text-[#8C7B70]">
            Trusted by clinics across India
          </p>
        </div>
      </div>
    </section>
  );
}
