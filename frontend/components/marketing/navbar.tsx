"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";

const navLinks = [
  { href: "/doctors", label: "Doctors" },
  { href: "/about", label: "About" },
  { href: "/features", label: "Product" },
  { href: "/pricing", label: "Pricing" },
  { href: "/contact", label: "Contact" },
];

export function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY >= 40);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={`fixed top-0 z-50 w-full transition-all duration-700 ease-out ${
        scrolled
          ? "bg-[#FAF8F5]/95 backdrop-blur-md border-b border-[#E8E2D9]"
          : "bg-transparent"
      }`}
    >
      <nav className="mx-auto flex h-[72px] max-w-7xl items-center justify-between px-8">
        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-3 group"
        >
          <div className="relative h-7 w-7">
            <svg viewBox="0 0 28 28" fill="none" className="h-7 w-7">
              <circle cx="14" cy="14" r="13" stroke="#2C2420" strokeWidth="1.5" />
              <path d="M14 7v14M7 14h14" stroke="#2C2420" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </div>
          <span className="font-serif text-[1.1rem] tracking-wide text-[#2C2420] leading-none">
            CareSync AI
          </span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden items-center gap-8 md:flex">
          {navLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`text-[13px] tracking-[0.04em] uppercase transition-colors duration-300 ${
                pathname === link.href
                  ? "text-[#2C2420]"
                  : "text-[#8C7B70] hover:text-[#2C2420]"
              }`}
            >
              {link.label}
            </Link>
          ))}
        </div>

        {/* Actions */}
        <div className="hidden items-center gap-3 md:flex">
          <Link
            href="/patient-signIn"
            className="inline-flex items-center gap-2 border border-[#2C2420] px-5 py-2 text-[12px] tracking-[0.08em] uppercase text-[#2C2420] transition-all duration-300 hover:bg-[#2C2420] hover:text-[#FAF8F5]"
          >
            Patient Portal
          </Link>
          <Link
            href="/signIn"
            className="inline-flex items-center gap-2 border border-[#2C2420] px-5 py-2 text-[12px] tracking-[0.08em] uppercase text-[#2C2420] transition-all duration-300 hover:bg-[#2C2420] hover:text-[#FAF8F5]"
          >
            Doctor Portal
          </Link>
        </div>

        {/* Mobile toggle */}
        <button
          className="flex h-10 w-10 flex-col items-center justify-center gap-[5px] md:hidden"
          onClick={() => setMobileOpen(!mobileOpen)}
          aria-label="Toggle menu"
        >
          <span
            className={`block h-px w-5 bg-[#2C2420] transition-all duration-300 ${
              mobileOpen ? "translate-y-[6px] rotate-45" : ""
            }`}
          />
          <span
            className={`block h-px w-5 bg-[#2C2420] transition-all duration-300 ${
              mobileOpen ? "opacity-0" : ""
            }`}
          />
          <span
            className={`block h-px w-5 bg-[#2C2420] transition-all duration-300 ${
              mobileOpen ? "-translate-y-[6px] -rotate-45" : ""
            }`}
          />
        </button>
      </nav>

      {/* Mobile menu */}
      <div
        className={`overflow-hidden transition-all duration-500 md:hidden ${
          mobileOpen ? "max-h-[400px]" : "max-h-0"
        }`}
      >
        <div className="border-t border-[#E8E2D9] bg-[#FAF8F5] px-8 py-6">
          <div className="flex flex-col gap-5">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-[13px] tracking-[0.08em] uppercase text-[#8C7B70] hover:text-[#2C2420] transition-colors"
                onClick={() => setMobileOpen(false)}
              >
                {link.label}
              </Link>
            ))}
            <div className="mt-3 flex flex-col gap-3 border-t border-[#E8E2D9] pt-5">
              <Link
                href="/signIn"
                className="inline-flex w-fit items-center border border-[#2C2420] px-6 py-2.5 text-[12px] tracking-[0.08em] uppercase text-[#2C2420]"
                onClick={() => setMobileOpen(false)}
              >
                Sign In
              </Link>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
