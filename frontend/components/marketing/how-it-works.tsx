import Link from "next/link";

const steps = [
  {
    index: "01",
    title: "Clinical Event Fires",
    body: "A lab result arrives, an appointment is missed, a prescription nears expiry. CareSync detects the trigger in real time.",
  },
  {
    index: "02",
    title: "AI Takes Action",
    body: "An AI voice agent calls the patient, explains the situation naturally, and offers to schedule a follow-up — no rigid phone trees.",
  },
  {
    index: "03",
    title: "Appointment Confirmed",
    body: "The booking lands directly on the physician's calendar and the patient receives a confirmation — all within 60 seconds.",
  },
];

const links = [
  { label: "How triggers work", href: "/features" },
  { label: "Call automation", href: "/features" },
  { label: "Booking integration", href: "/features" },
];

export function HowItWorks() {
  return (
    <section className="bg-[#2C2420] py-28 md:py-36">
      <div className="mx-auto max-w-7xl px-8">
        {/* Section header */}
        <div className="flex items-center gap-4 mb-16">
          <span className="h-px w-8 bg-[#8C7B70]" />
          <p className="text-[11px] tracking-[0.22em] uppercase text-[#8C7B70]">
            Our Approach
          </p>
        </div>

        <div className="grid gap-16 lg:grid-cols-[1fr_1fr] lg:gap-24 lg:items-start">
          {/* Left: headline */}
          <div>
            <h2 className="font-serif text-[clamp(2.2rem,4vw,3.4rem)] leading-[1.1] tracking-tight text-[#FAF8F5]">
              We automate the gap between clinical events and patient action.
            </h2>
            <p className="mt-6 max-w-md text-[15px] leading-[1.8] text-[#8C7B70]">
              When something happens in your clinic — CareSync AI bridges the distance
              to your patient so your staff doesn&apos;t have to.
            </p>

            {/* Link list */}
            <div className="mt-12 border-t border-[#3D3028]">
              {links.map((link) => (
                <Link
                  key={link.label}
                  href={link.href}
                  className="group flex items-center justify-between border-b border-[#3D3028] py-4 text-[13px] tracking-[0.04em] text-[#8C7B70] transition-colors hover:text-[#FAF8F5]"
                >
                  {link.label}
                  <svg
                    className="h-4 w-4 opacity-0 transition-all duration-300 group-hover:opacity-100 group-hover:translate-x-1"
                    fill="none"
                    viewBox="0 0 16 16"
                    stroke="currentColor"
                    strokeWidth={1.5}
                  >
                    <path d="M2 8h12M9 3l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </Link>
              ))}
            </div>
          </div>

          {/* Right: step cards */}
          <div className="space-y-0">
            {steps.map((step, i) => (
              <div
                key={step.index}
                className={`flex gap-8 py-10 ${
                  i < steps.length - 1 ? "border-b border-[#3D3028]" : ""
                }`}
              >
                <span className="font-serif text-[11px] tracking-[0.1em] text-[#8C7B70] pt-1 w-8 shrink-0">
                  {step.index}
                </span>
                <div>
                  <h3 className="font-serif text-xl text-[#FAF8F5] leading-snug">
                    {step.title}
                  </h3>
                  <p className="mt-3 text-[14px] leading-[1.75] text-[#8C7B70]">
                    {step.body}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
