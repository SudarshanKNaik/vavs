"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

export function Hero() {
  const lineRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = lineRef.current;
    if (!el) return;
    // Animate the horizontal rule on mount
    el.style.transform = "scaleX(0)";
    el.style.transformOrigin = "left";
    el.style.transition = "transform 1.4s cubic-bezier(0.16, 1, 0.3, 1) 0.6s";
    requestAnimationFrame(() => {
      el.style.transform = "scaleX(1)";
    });
  }, []);

  return (
    <section className="relative h-[100svh] bg-[#FAF8F5] overflow-hidden">
      {/* Fine-grain texture overlay */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
          backgroundRepeat: "repeat",
          backgroundSize: "200px",
        }}
        aria-hidden="true"
      />

      {/* Subtle radial warmth top-right */}
      <div
        className="pointer-events-none absolute -top-40 right-0 h-[700px] w-[700px] rounded-full opacity-25"
        style={{
          background: "radial-gradient(circle, #F0E6D3 0%, transparent 70%)",
        }}
        aria-hidden="true"
      />

      {/* Thin vertical rule — editorial column marker */}
      <div className="pointer-events-none absolute left-[56px] top-0 hidden h-full w-px bg-[#E8E2D9] lg:block" aria-hidden="true" />

      <div className="relative mx-auto h-full max-w-7xl px-6 pt-28 pb-12 md:px-8 md:pt-32 md:pb-16">
        <div className="grid h-full grid-cols-1 gap-10 md:grid-cols-[minmax(0,460px)_minmax(0,1fr)] md:gap-8">
          {/* Left content */}
          <div className="flex h-full min-h-0 flex-col justify-between pr-0 md:pr-10">
            <div>
              {/* Top label */}
              <div
                className="flex items-center gap-3 animate-fade-in"
                style={{ animationDelay: "0.1s", opacity: 0, animation: "fadeInUp 0.8s ease forwards 0.1s" }}
              >
                <span className="h-px w-8 bg-[#6E6057]" />
                <p className="text-[11px] font-medium tracking-[0.22em] uppercase text-[#6E6057]">
                  Clinical Workflow Automation
                </p>
              </div>

              {/* Main headline */}
              <h1
                className="mt-8 font-serif font-medium text-[clamp(2.6rem,5vw,5rem)] leading-[1.0] tracking-[-0.01em] text-[#1F1916]"
                style={{
                  animation: "fadeInUp 1s ease forwards 0.25s",
                  opacity: 0,
                  textShadow: "0 1px 0 rgba(255,255,255,0.28)",
                }}
              >
                Medicine moves fast.
                <br />
                <em className="italic text-[#5E5149]">Your workflows</em>
                <br />
                should too.
              </h1>

              {/* Animated hairline */}
              <div
                ref={lineRef}
                className="mt-10 h-px max-w-md bg-[#D4C9BB]"
              />

              {/* Sub-copy */}
              <p
                className="mt-8 max-w-sm text-[15px] font-medium leading-[1.75] text-[#5E5149]"
                style={{ animation: "fadeInUp 1s ease forwards 0.6s", opacity: 0 }}
              >
                From patient outreach and follow-ups to scheduling and referrals -
                CareSync AI automates every step so nothing falls through the cracks.
              </p>
            </div>

            <div
              className="mt-10"
              style={{ animation: "fadeInUp 1s ease forwards 0.9s", opacity: 0 }}
            >
              <div className="flex items-center gap-6">
                <Link
                  href="/signIn"
                  className="inline-flex items-center gap-3 group"
                >
                  <span className="text-[13px] tracking-[0.08em] uppercase text-[#2C2420] border-b border-[#2C2420] pb-0.5 transition-all duration-300 group-hover:border-transparent group-hover:text-[#8C7B70]">
                    Get Started
                  </span>
                  <svg
                    className="h-4 w-4 text-[#2C2420] transition-transform duration-300 group-hover:translate-x-1"
                    fill="none"
                    viewBox="0 0 16 16"
                    stroke="currentColor"
                    strokeWidth={1.5}
                  >
                    <path d="M2 8h12M9 3l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </Link>
                <Link
                  href="/features"
                  className="text-[13px] tracking-[0.08em] uppercase text-[#6E6057] hover:text-[#2C2420] transition-colors duration-300"
                >
                  See how it works
                </Link>
              </div>

              {/* Bottom stats strip */}
              <div className="mt-10 grid grid-cols-3 border-t border-[#E8E2D9] pt-6">
                {[
                  { value: "< 5min", label: "First contact" },
                  { value: "30%", label: "Fewer no-shows" },
                  { value: "99.9%", label: "Uptime" },
                ].map((stat) => (
                  <div key={stat.label} className="pr-4">
                    <p className="font-serif text-2xl text-[#2C2420]">{stat.value}</p>
                    <p className="mt-1 text-[11px] tracking-[0.1em] uppercase text-[#6E6057]">
                      {stat.label}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Right video */}
          <div className="relative hidden h-full min-h-0 items-start justify-center overflow-hidden md:flex">
            <div
              className="relative h-full w-full"
              style={{
                maxWidth: 600,
                overflow: "hidden",
                maskImage: "linear-gradient(to bottom, black 0%, black 74%, transparent 100%)",
                WebkitMaskImage: "linear-gradient(to bottom, black 0%, black 74%, transparent 100%)",
              }}
            >
              <video
                autoPlay
                loop
                muted
                playsInline
                className="block h-full w-full"
                style={{
                  objectFit: "cover",
                  objectPosition: "center top",
                  transform: "scale(1.08)",
                }}
              >
                <source src="/ajja.mp4" type="video/mp4" />
              </video>
            </div>
          </div>
        </div>
      </div>

      {/* Full-bleed decorative bottom rule */}
      <div className="absolute bottom-0 left-0 right-0 h-px bg-[#E8E2D9]" />

      <style jsx>{`
        @keyframes fadeInUp {
          from {
            opacity: 0;
            transform: translateY(18px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
      `}</style>
    </section>
  );
}
