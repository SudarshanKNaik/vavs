"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  FileText,
  Phone,
  CalendarCheck,
  RotateCcw,
  Droplet,
  MapPin,
  MessageSquare,
  Radar,
  Languages,
  IndianRupee,
  ShieldCheck,
  ArrowRight,
  ArrowDown,
  Clock,
  Users,
  Activity,
} from "lucide-react";

// Every claim on these slides maps to code in this repo or to a sourced
// figure; modelled numbers are labelled as such. The written business case
// (assumptions, sources, Q&A) lives alongside the deck.
const TOTAL_SLIDES = 12;

export default function PitchDeck() {
  const [current, setCurrent] = useState(0);
  const [direction, setDirection] = useState<"next" | "prev">("next");

  const goTo = useCallback(
    (n: number) => {
      if (n < 0 || n >= TOTAL_SLIDES || n === current) return;
      setDirection(n > current ? "next" : "prev");
      setCurrent(n);
    },
    [current],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        goTo(current + 1);
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        goTo(current - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [current, goTo]);

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-background">
      {/* Slide indicator dots */}
      <div className="fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 gap-2">
        {Array.from({ length: TOTAL_SLIDES }).map((_, i) => (
          <button
            key={i}
            onClick={() => goTo(i)}
            aria-label={`Go to slide ${i + 1}`}
            className={`h-2 rounded-full transition-all duration-300 ${
              i === current
                ? "w-8 bg-primary"
                : "w-2 bg-sage-400 hover:bg-sage-600"
            }`}
          />
        ))}
      </div>

      {/* Slide number */}
      <div className="fixed bottom-6 right-8 z-50 font-mono text-sm text-sage-400">
        {current + 1} / {TOTAL_SLIDES}
      </div>

      {/* ── Slide 1: Title ── */}
      <Slide index={0} current={current} direction={direction}>
        <div className="bg-grid flex h-full flex-col items-center justify-center px-8 text-center">
          <div className="mb-8 flex items-center gap-4">
            <Image
              src="/assets/Clarus.png"
              alt="CareSync AI"
              width={80}
              height={80}
              className="h-20 w-20"
            />
            <span className="font-serif text-8xl font-bold tracking-tight text-foreground">
              CareSync AI
            </span>
          </div>
          <div className="mb-8 h-1 w-32 rounded-full bg-primary" />
          <p className="mb-12 max-w-3xl font-serif text-3xl leading-relaxed tracking-tight text-muted-foreground">
            Every call closes a loop, and makes the next one smarter.
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <Pill>Patient follow-up</Pill>
            <Pill>Emergency blood</Pill>
            <Pill>Outbreak early warning</Pill>
          </div>
          <p className="mt-10 rounded-full border border-border bg-card/80 px-6 py-2 text-sm uppercase tracking-[0.2em] text-sage-500">
            Built for Indian hospitals · Hubli–Dharwad
          </p>
        </div>
      </Slide>

      {/* ── Slide 2: The Problem ── */}
      <Slide index={1} current={current} direction={direction}>
        <SlideFrame
          eyebrow="The problem"
          title="Three hospital jobs still run on phones and luck"
          footer="Sources: Caller Digital 2026 (vendor estimate); ORF citing BMJ; PMC South India dengue cohort"
        >
          <div className="grid grid-cols-3 gap-6">
            <ProblemCard
              icon={<FileText className="h-5 w-5" />}
              title="Follow-up"
              body="An abnormal lab waits for a free phone line, a free hour and the patient's language."
              stat="26–32%"
              statLabel="of scheduled OPD visits never happen (industry estimate)"
            />
            <ProblemCard
              icon={<Droplet className="h-5 w-5" />}
              title="Blood"
              body="Families phone donors and banks one number at a time, often from stale stock lists."
              stat="~22%"
              statLabel="of blood banks rarely or never update e-RaktKosh"
            />
            <ProblemCard
              icon={<Activity className="h-5 w-5" />}
              title="Outbreaks"
              body="Dengue clusters fill wards before they show up in surveillance reports."
              stat="7×"
              statLabel="rise in reported dengue cases, 2010 to 2024 (28k to 200k+)"
            />
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 3: Why now ── */}
      <Slide index={2} current={current} direction={direction}>
        <SlideFrame
          eyebrow="Why now"
          title="A phone call can now do a coordinator's work"
          footer="Sources: ElevenLabs agent pricing 2026 (third-party summaries); CareSync code"
        >
          <div className="divide-y divide-border border-y border-border">
            <FactRow
              value="₹9–13 / min"
              text="Conversational voice AI costs about this today and fell again in 2026. An Indian voice stack takes it to about ₹4–6."
            />
            <FactRow
              value="13 languages"
              text="Our call engine accepts 13 Indian languages and remembers each patient's. Kannada, Hindi and English are live on our agent."
            />
            <FactRow
              value="DPDP 2023"
              text="Clear consent rules mean health data products can be built properly: consent, purpose and opt-out from day one."
            />
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 4: One engine, three loops ── */}
      <Slide index={3} current={current} direction={direction}>
        <SlideFrame
          eyebrow="The solution"
          title="One engine. Event in, outcome out."
          footer="Every loop runs on the same calls, so every call also feeds the outbreak signal"
        >
          <div className="grid grid-cols-3 gap-6">
            <LoopBox title="1 · Follow-up" body="Abnormal lab or missed visit" />
            <LoopBox title="2 · Blood" body="Group, units, 20 km radius" />
            <LoopBox title="3 · Outbreak Watch" body="Symptoms heard on every call" />
          </div>
          <DownArrows />
          <div className="rounded-2xl border-2 border-primary bg-primary/10 px-8 py-5 text-center font-serif text-2xl font-bold text-foreground">
            Vernacular voice engine · parallel calls · retries · SMS + email
          </div>
          <DownArrows />
          <div className="grid grid-cols-3 gap-6">
            <LoopBox solid title="Slot booked" body="Confirmed by email; retried if missed" />
            <LoopBox solid title="Unit confirmed" body="Nearest bank or donor, SMS sent" />
            <LoopBox solid title="Area alert" body="Dengue rise → platelet forecast → blood loop" />
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 5: Loop 1, follow-up ── */}
      <Slide index={4} current={current} direction={direction}>
        <SlideFrame
          eyebrow="Loop 1 · Follow-up · built"
          title="Lab in. Patient called. Slot booked."
          footer="Staff-minute figures are our model; the pilot will measure them"
        >
          <div className="grid grid-cols-5 gap-8">
            <ol className="col-span-3 space-y-5">
              <BulletPoint icon={<FileText className="h-5 w-5" />}>
                <b>Report arrives</b> as a PDF or photo; values are extracted and abnormal ones flagged
              </BulletPoint>
              <BulletPoint icon={<Languages className="h-5 w-5" />}>
                <b>AI call</b> in the patient&apos;s remembered language, with the report and open slots
              </BulletPoint>
              <BulletPoint icon={<CalendarCheck className="h-5 w-5" />}>
                <b>Slot booked on the call</b>, with an email confirmation and calendar sync
              </BulletPoint>
              <BulletPoint icon={<RotateCcw className="h-5 w-5" />}>
                <b>No booking?</b> The scheduler retries automatically
              </BulletPoint>
            </ol>
            <div className="col-span-2 flex flex-col rounded-2xl bg-foreground p-8 text-background">
              <p className="text-xs font-bold uppercase tracking-[0.25em] text-primary">
                Demo story
              </p>
              {/* TODO: replace with the team's follow-up demo scenario */}
              <p className="mt-4 text-xl leading-relaxed">
                [Your follow-up scenario: patient, result, language and outcome]
              </p>
              <p className="mt-auto pt-6 text-sm opacity-80">
                Staff time per follow-up: about 8 min manually, under 1 min with
                CareSync (exceptions only)
              </p>
            </div>
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 6: Loop 2, blood ── */}
      <Slide index={5} current={current} direction={direction}>
        <SlideFrame
          eyebrow="Loop 2 · Blood · demoed live"
          title="Three nearest banks or donors, called at once"
          footer="We ask the bank live instead of trusting a stock portal that may be days old"
        >
          <div className="grid grid-cols-3 gap-5">
            <FeatureCard icon={<Users className="h-5 w-5" />} title="Choose the source" body="Donors, blood banks, or any, nearest first" />
            <FeatureCard icon={<MapPin className="h-5 w-5" />} title="20 km radius" body="Distance from the hospital, computed on our own data" />
            <FeatureCard icon={<Phone className="h-5 w-5" />} title="3 calls at once" body="Rolling batches until someone says yes" />
            <FeatureCard icon={<RotateCcw className="h-5 w-5" />} title="Hang-up? One retry" body="Twilio tells us who never answered; a second hang-up drops them" />
            <FeatureCard icon={<Droplet className="h-5 w-5" />} title="First yes stops it" body="Units confirmed and logged per blood bank" />
            <FeatureCard accent icon={<MessageSquare className="h-5 w-5" />} title="SMS + email" body="Where to go and whom to ask; summary to the doctor" />
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 7: Loop 3, Outbreak Watch ── */}
      <Slide index={6} current={current} direction={direction}>
        <SlideFrame
          eyebrow="Loop 3 · Outbreak Watch · built"
          title="The calls we already make become an early-warning map"
          footer="Poisson test against each area's own baseline; at least 3 cases to watch, 5 to alert"
        >
          <div className="grid grid-cols-4 gap-4">
            <StageCard title="1 · Listen" body="Symptoms patients mention on calls, in English, Hindi and Kannada (negation-aware)" />
            <StageCard title="2 · Group" body="Dengue-like, respiratory and gastro syndromes, by locality" />
            <StageCard title="3 · Test" body="Last 7 days against the area's own 28 days; watch at p < 0.05, alert at p < 0.01" />
            <StageCard accent title="4 · Act" body="Red/amber map zones, a platelet forecast for the blood loop, a report to the health officer" />
          </div>
          <p className="mt-8 text-lg text-foreground">
            <b>Zero marginal cost:</b> it runs on calls the hospital already pays for.
            Reports are aggregate-only, with no patient details.
          </p>
        </SlideFrame>
      </Slide>

      {/* ── Slide 8: What's new ── */}
      <Slide index={7} current={current} direction={direction}>
        <SlideFrame
          eyebrow="What's new"
          title="Others own one step. We own the loop and its data."
          footer="Sources: The Bio Startups (Voiceoc, 2026); ORF citing BMJ; The Bastion on IDSP"
        >
          <table className="w-full text-left text-base">
            <thead>
              <tr className="border-b-2 border-foreground text-sm uppercase tracking-wider text-muted-foreground">
                <th className="py-3 pr-4">Who</th>
                <th className="py-3 pr-4">Does</th>
                <th className="py-3">Misses</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border text-foreground">
              <CompetitorRow who="Hospital voicebots (Voiceoc, Caller Digital)" does="Reminders, FAQs" misses="Not triggered by lab results; no blood; no surveillance" />
              <CompetitorRow who="Practo, Eka Care" does="Records, booking" misses="Patient must come to them; no outbound loop" />
              <CompetitorRow who="e-RaktKosh" does="Stock portal" misses="~22% of banks rarely update; nobody calls for you" />
              <CompetitorRow who="Donor apps, WhatsApp" does="Donor lists" misses="Family still dials one by one; no retries or radius" />
              <CompetitorRow who="IDSP / IHIP" does="Official reporting" misses="Facility reports only; dengue under-reporting documented" />
              <tr className="bg-primary/10 font-semibold">
                <td className="py-3 pr-4">CareSync AI</td>
                <td className="py-3 pr-4">Event to outcome</td>
                <td className="py-3">Every call also feeds outbreak data and a supplier-trust record</td>
              </tr>
            </tbody>
          </table>
        </SlideFrame>
      </Slide>

      {/* ── Slide 9: Business case ── */}
      <Slide index={8} current={current} direction={direction}>
        <SlideFrame
          eyebrow="Business case · India, in rupees"
          title="≈ ₹1.5 lakh a month for a 200-bed hospital"
          footer="Model inputs: front-desk pay ₹12–22k/month; ElevenLabs ~$0.08–0.10/min; FX ₹88. A pilot replaces the assumptions"
        >
          <div className="grid grid-cols-2 gap-10">
            <div>
              <h3 className="mb-3 font-serif text-2xl font-bold text-foreground">Per completed follow-up</h3>
              <table className="w-full text-left text-base text-foreground">
                <thead>
                  <tr className="border-b-2 border-foreground text-sm uppercase tracking-wider text-muted-foreground">
                    <th className="py-2" />
                    <th className="py-2 text-right">Manual</th>
                    <th className="py-2 text-right">CareSync</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  <MoneyRow label="Cost" a="≈ ₹20" b="≈ ₹23–30" />
                  <MoneyRow label="On Indian voice stack" a="≈ ₹20" b="≈ ₹10–14" />
                  <MoneyRow label="Staff minutes" a="8" b="< 1" />
                </tbody>
              </table>
              <p className="mt-4 text-base text-muted-foreground">
                <b className="text-foreground">Honest:</b> per minute, AI isn&apos;t
                cheaper yet. The win is capacity, completion and speed.
              </p>
            </div>
            <div>
              <h3 className="mb-3 font-serif text-2xl font-bold text-foreground">Base case, per month</h3>
              <table className="w-full text-left text-base text-foreground">
                <tbody className="divide-y divide-border">
                  <MoneyRow label="375 extra follow-ups × ₹500" b="+₹1,87,500" />
                  <MoneyRow label="100 staff hours freed" b="+₹14,800" />
                  <MoneyRow label="CareSync subscription + usage" b="−₹49,249" />
                  <tr className="bg-primary/10 font-bold">
                    <td className="py-2">Net to the hospital</td>
                    <td className="py-2 text-right">≈ +₹1,53,000</td>
                  </tr>
                </tbody>
              </table>
              <p className="mt-4 text-sm text-muted-foreground">
                1,500 follow-up events a month, with completion rising from 50% to 75%.
                Conservative case ≈ ₹6,800; optimistic ≈ ₹7.4 lakh.
              </p>
            </div>
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 10: Business model ── */}
      <Slide index={9} current={current} direction={direction}>
        <SlideFrame
          eyebrow="Business model · go-to-market"
          title="Hospitals pay. Donors and families never do."
          footer="Proposed prices; gross margin rises from about 23% to 65% on an Indian voice stack"
        >
          <div className="grid grid-cols-4 gap-5">
            <PriceCard plan="Hospital" price="₹34,999/mo" note="2,500 min included, then ₹15/min" />
            <PriceCard plan="Clinic" price="₹4,999/mo" note="500 min, follow-up loop" />
            <PriceCard plan="Blood" price="₹149/unit" note="Per confirmed unit, paid by the hospital" />
            <PriceCard plan="District" price="₹0.5–1L/yr" note="Outbreak dashboard licence" />
          </div>
          <div className="mt-10 grid grid-cols-3 gap-6">
            <Phase accent when="0–3 months" what="Pilot in Hubli–Dharwad: 1–2 hospitals and a blood centre" />
            <Phase when="3–12 months" what="Tier-2 Karnataka through hospital networks and NGOs" />
            <Phase when="12 months +" what="District health offices buy the outbreak layer" />
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 11: Built vs next ── */}
      <Slide index={10} current={current} direction={direction}>
        <SlideFrame
          eyebrow="Proof · honesty · next"
          title="Built and tested now; hardened next"
          footer="Known limits today: plain-text passwords (demo only); Twilio trial reaches verified numbers only"
        >
          <div className="grid grid-cols-2 gap-10">
            <div>
              <h3 className="mb-4 font-serif text-2xl font-bold text-foreground">Working today</h3>
              <ul className="space-y-4">
                <BulletPoint icon={<Phone className="h-5 w-5" />}>Parallel live calls to 3 real phones</BulletPoint>
                <BulletPoint icon={<RotateCcw className="h-5 w-5" />}>Hang-up detection via Twilio, auto-retry</BulletPoint>
                <BulletPoint icon={<MessageSquare className="h-5 w-5" />}>SMS + email to whoever said yes</BulletPoint>
                <BulletPoint icon={<Radar className="h-5 w-5" />}>Outbreak map with Poisson alerts</BulletPoint>
                <BulletPoint icon={<ShieldCheck className="h-5 w-5" />}>72 automated backend tests</BulletPoint>
              </ul>
            </div>
            <div>
              <h3 className="mb-4 font-serif text-2xl font-bold text-foreground">Next 90 days</h3>
              <ul className="space-y-4">
                <BulletPoint icon={<ShieldCheck className="h-5 w-5" />}>Auth hardening: hashed passwords, sessions</BulletPoint>
                <BulletPoint icon={<Users className="h-5 w-5" />}>Donor self-registration with DPDP consent</BulletPoint>
                <BulletPoint icon={<Clock className="h-5 w-5" />}>Persistent dispatch on the job table</BulletPoint>
                <BulletPoint icon={<IndianRupee className="h-5 w-5" />}>Indian voice + DLT SMS stack</BulletPoint>
                <BulletPoint icon={<Activity className="h-5 w-5" />}>Pilot metrics: time to blood, completion</BulletPoint>
              </ul>
            </div>
          </div>
        </SlideFrame>
      </Slide>

      {/* ── Slide 12: Ask + live demo ── */}
      <Slide index={11} current={current} direction={direction}>
        <div className="bg-grid flex h-full flex-col items-center justify-center px-8 text-center">
          <p className="mb-4 text-sm font-bold uppercase tracking-[0.25em] text-primary">
            The ask
          </p>
          <h2 className="mb-4 max-w-5xl font-serif text-6xl font-bold tracking-tight text-foreground">
            One hospital. One blood centre. Three months.
          </h2>
          <div className="mb-8 h-1 w-24 rounded-full bg-primary" />
          <p className="mb-12 max-w-2xl text-xl text-muted-foreground">
            Help us pilot in Hubli–Dharwad and measure time to blood, follow-up
            completion and staff minutes saved.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <DemoLink href="/blood-requests" label="Live: raise a blood request" />
            <DemoLink href="/outbreak-watch" label="Live: outbreak map" />
            <DemoLink href="/triggers" label="Live: follow-up workflows" />
          </div>
        </div>
      </Slide>
    </div>
  );
}

/* ── Sub-components ── */

function Slide({
  index,
  current,
  direction,
  children,
}: {
  index: number;
  current: number;
  direction: "next" | "prev";
  children: React.ReactNode;
}) {
  const isActive = index === current;
  const isPast = index < current;

  let translate = "translate-x-full";
  if (isActive) translate = "translate-x-0";
  else if (isPast) translate = "-translate-x-full";

  if (!isActive) {
    if (direction === "prev") {
      translate = isPast ? "-translate-x-full" : "translate-x-full";
    }
  }

  return (
    <div
      className={`absolute inset-0 transition-all duration-500 ease-in-out ${translate} ${
        isActive ? "opacity-100" : "opacity-0"
      }`}
    >
      {children}
    </div>
  );
}

function SlideFrame({
  eyebrow,
  title,
  footer,
  children,
}: {
  eyebrow: string;
  title: string;
  footer?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex h-full flex-col justify-center px-16 py-12">
      <p className="mb-2 text-sm font-bold uppercase tracking-[0.25em] text-primary">
        {eyebrow}
      </p>
      <h2 className="mb-2 max-w-6xl font-serif text-5xl font-bold leading-[1.1] tracking-tight text-foreground">
        {title}
      </h2>
      <div className="mb-10 h-1 w-24 rounded-full bg-primary" />
      {children}
      {footer && (
        <p className="absolute bottom-14 left-16 max-w-5xl text-xs text-sage-500">
          {footer}
        </p>
      )}
    </div>
  );
}

function Pill({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-primary/30 bg-primary/5 px-5 py-2 text-base font-medium text-foreground">
      {children}
    </span>
  );
}

function BulletPoint({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-4">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
        {icon}
      </span>
      <span className="text-lg leading-relaxed text-foreground">{children}</span>
    </li>
  );
}

function ProblemCard({
  icon,
  title,
  body,
  stat,
  statLabel,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  stat: string;
  statLabel: string;
}) {
  return (
    <div className="flex flex-col rounded-2xl border border-border bg-card/80 p-7 shadow-sm">
      <div className="mb-3 flex items-center gap-3 text-primary">
        {icon}
        <h3 className="font-serif text-2xl font-bold text-foreground">{title}</h3>
      </div>
      <p className="mb-6 text-base leading-relaxed text-muted-foreground">{body}</p>
      <p className="mt-auto font-serif text-5xl font-bold tracking-tight text-primary">
        {stat}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{statLabel}</p>
    </div>
  );
}

function FactRow({ value, text }: { value: string; text: string }) {
  return (
    <div className="flex items-baseline gap-10 py-6">
      <p className="w-64 shrink-0 font-serif text-4xl font-bold tracking-tight text-foreground">
        {value}
      </p>
      <p className="text-lg leading-relaxed text-muted-foreground">{text}</p>
    </div>
  );
}

function LoopBox({
  title,
  body,
  solid,
}: {
  title: string;
  body: string;
  solid?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl px-6 py-4 ${
        solid ? "bg-foreground text-background" : "border border-border bg-card/80"
      }`}
    >
      <p className="font-serif text-xl font-bold">{title}</p>
      <p className={`text-sm ${solid ? "opacity-80" : "text-muted-foreground"}`}>{body}</p>
    </div>
  );
}

function DownArrows() {
  return (
    <div className="grid grid-cols-3 gap-6 py-2">
      {[0, 1, 2].map((i) => (
        <ArrowDown key={i} className="mx-auto h-6 w-6 text-sage-400" />
      ))}
    </div>
  );
}

function FeatureCard({
  icon,
  title,
  body,
  accent,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl p-6 ${
        accent
          ? "bg-primary text-primary-foreground"
          : "border border-border bg-card/80 text-foreground"
      }`}
    >
      <div className={`mb-2 flex items-center gap-2 ${accent ? "" : "text-primary"}`}>
        {icon}
        <h3 className="font-serif text-xl font-bold">{title}</h3>
      </div>
      <p className={`text-base ${accent ? "opacity-90" : "text-muted-foreground"}`}>{body}</p>
    </div>
  );
}

function StageCard({
  title,
  body,
  accent,
}: {
  title: string;
  body: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl border-t-4 bg-card/80 p-5 shadow-sm ${
        accent ? "border-primary" : "border-foreground"
      }`}
    >
      <p className={`font-serif text-2xl font-bold ${accent ? "text-primary" : "text-foreground"}`}>
        {title}
      </p>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}

function CompetitorRow({
  who,
  does,
  misses,
}: {
  who: string;
  does: string;
  misses: string;
}) {
  return (
    <tr>
      <td className="py-3 pr-4 font-medium">{who}</td>
      <td className="py-3 pr-4 text-muted-foreground">{does}</td>
      <td className="py-3 text-muted-foreground">{misses}</td>
    </tr>
  );
}

function MoneyRow({ label, a, b }: { label: string; a?: string; b: string }) {
  return (
    <tr>
      <td className="py-2">{label}</td>
      {a !== undefined && <td className="py-2 text-right">{a}</td>}
      <td className="py-2 text-right font-semibold">{b}</td>
    </tr>
  );
}

function PriceCard({ plan, price, note }: { plan: string; price: string; note: string }) {
  return (
    <div className="rounded-2xl border border-border bg-card/80 p-6 shadow-sm">
      <p className="text-xs font-bold uppercase tracking-[0.2em] text-sage-500">{plan}</p>
      <p className="mt-2 font-serif text-3xl font-bold text-foreground">{price}</p>
      <p className="mt-2 text-sm text-muted-foreground">{note}</p>
    </div>
  );
}

function Phase({ when, what, accent }: { when: string; what: string; accent?: boolean }) {
  return (
    <div className={`border-t-4 pt-4 ${accent ? "border-primary" : "border-foreground"}`}>
      <p className={`text-sm font-bold ${accent ? "text-primary" : "text-foreground"}`}>{when}</p>
      <p className="mt-1 text-base text-muted-foreground">{what}</p>
    </div>
  );
}

function DemoLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="group inline-flex items-center gap-3 rounded-2xl bg-primary px-8 py-4 text-lg font-semibold text-primary-foreground shadow-lg transition-all duration-200 hover:scale-105 hover:shadow-xl"
    >
      {label}
      <ArrowRight className="h-5 w-5 transition-transform group-hover:translate-x-1" />
    </Link>
  );
}
