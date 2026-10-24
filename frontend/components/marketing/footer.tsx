import Link from "next/link";

const productLinks = [
  { label: "Features", href: "/features" },
  { label: "Pricing", href: "/pricing" },
  { label: "Doctors", href: "/doctors" },
  { label: "Contact", href: "/contact" },
];

const companyLinks = [
  { label: "About", href: "/about" },
  { label: "Privacy", href: "#" },
  { label: "Terms", href: "#" },
];

const portalLinks = [
  { label: "Physician Sign In", href: "/signIn" },
  { label: "Patient Portal", href: "/patient-signIn" },
];

export function Footer() {
  return (
    <footer className="bg-[#FAF8F5] border-t border-[#E8E2D9]">
      {/* Main footer */}
      <div className="mx-auto max-w-7xl px-8 py-16">
        <div className="grid gap-12 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr_1fr]">
          {/* Brand column */}
          <div>
            <div className="flex items-center gap-3">
              <svg viewBox="0 0 28 28" fill="none" className="h-6 w-6 shrink-0">
                <circle cx="14" cy="14" r="13" stroke="#2C2420" strokeWidth="1.5" />
                <path d="M14 7v14M7 14h14" stroke="#2C2420" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <span className="font-serif text-lg tracking-wide text-[#2C2420]">
                CareSync AI
              </span>
            </div>
            <p className="mt-4 max-w-xs text-[13px] leading-[1.75] text-[#8C7B70]">
              Intelligent clinical workflow automation. From trigger to booking in
              under five minutes.
            </p>

            {/* Trust badges */}
            <div className="mt-8 flex flex-wrap gap-3">
              {["HIPAA Ready", "99.9% Uptime", "SOC 2 Aligned"].map((badge) => (
                <span
                  key={badge}
                  className="inline-flex items-center border border-[#D4C9BB] px-3 py-1 text-[10px] tracking-[0.14em] uppercase text-[#8C7B70]"
                >
                  {badge}
                </span>
              ))}
            </div>
          </div>

          {/* Product links */}
          <div>
            <p className="text-[10px] tracking-[0.2em] uppercase text-[#A0907F] mb-5">
              Product
            </p>
            <div className="flex flex-col gap-3">
              {productLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="text-[13px] text-[#8C7B70] hover:text-[#2C2420] transition-colors duration-200"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>

          {/* Company links */}
          <div>
            <p className="text-[10px] tracking-[0.2em] uppercase text-[#A0907F] mb-5">
              Company
            </p>
            <div className="flex flex-col gap-3">
              {companyLinks.map((link) => (
                <Link
                  key={link.label}
                  href={link.href}
                  className="text-[13px] text-[#8C7B70] hover:text-[#2C2420] transition-colors duration-200"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>

          {/* Portal links */}
          <div>
            <p className="text-[10px] tracking-[0.2em] uppercase text-[#A0907F] mb-5">
              Portals
            </p>
            <div className="flex flex-col gap-3">
              {portalLinks.map((link) => (
                <Link
                  key={link.label}
                  href={link.href}
                  className="text-[13px] text-[#8C7B70] hover:text-[#2C2420] transition-colors duration-200"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div className="border-t border-[#E8E2D9]">
        <div className="mx-auto max-w-7xl px-8 py-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[11px] tracking-[0.08em] text-[#A0907F]">
            &copy; {new Date().getFullYear()} CareSync AI Inc. All rights reserved.
          </p>
          <p className="text-[11px] tracking-[0.06em] text-[#A0907F]">
            Built for clinics that care about their patients.
          </p>
        </div>
      </div>
    </footer>
  );
}
