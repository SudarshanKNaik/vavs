const features = [
  {
    tag: "Automation",
    title: "Smart Triggers",
    body: "Configure event-driven automations tied to clinical events — lab results, missed appointments, expiring prescriptions. Set conditions per doctor or clinic-wide.",
    detail: "Fires in under 30 seconds",
  },
  {
    tag: "Communication",
    title: "AI Voice Calls",
    body: "An AI agent speaks naturally with patients, explains why the doctor is reaching out, and schedules appointments conversationally — no rigid phone menus.",
    detail: "Natural language, zero IVR",
  },
  {
    tag: "Scheduling",
    title: "Instant Booking",
    body: "Appointments are booked directly to Google Calendar the moment a patient confirms. No back-and-forth, no manual entry.",
    detail: "Syncs in real time",
  },
  {
    tag: "Outreach",
    title: "Multi-channel Follow-ups",
    body: "If a call is unanswered, CareSync queues an SMS or email follow-up automatically — with configurable retry intervals and escalation rules.",
    detail: "SMS, Email, Voice",
  },
];

export function FeaturesSection() {
  return (
    <section className="bg-[#FAF8F5] py-28 md:py-36">
      <div className="mx-auto max-w-7xl px-8">
        {/* Section header */}
        <div className="flex items-center justify-between border-b border-[#E8E2D9] pb-8">
          <div className="flex items-center gap-4">
            <span className="h-px w-8 bg-[#8C7B70]" />
            <p className="text-[11px] tracking-[0.22em] uppercase text-[#8C7B70]">
              Product
            </p>
          </div>
          <h2 className="font-serif text-[clamp(1.8rem,3.5vw,2.8rem)] text-[#2C2420] tracking-tight">
            What CareSync does
          </h2>
        </div>

        {/* Feature grid */}
        <div className="mt-0 grid grid-cols-1 divide-y divide-[#E8E2D9] md:grid-cols-2 md:divide-y-0">
          {features.map((feature, i) => (
            <div
              key={feature.title}
              className={`group py-12 pr-0 transition-colors duration-300 ${
                i % 2 === 0 ? "md:pr-16 md:border-r md:border-[#E8E2D9]" : "md:pl-16"
              } ${
                i < 2 ? "md:border-b md:border-[#E8E2D9]" : ""
              }`}
            >
              {/* Tag */}
              <div className="flex items-center gap-3 mb-6">
                <span className="text-[10px] tracking-[0.2em] uppercase text-[#8C7B70] border border-[#D4C9BB] px-2.5 py-1">
                  {feature.tag}
                </span>
              </div>

              <h3 className="font-serif text-[1.6rem] leading-tight tracking-tight text-[#2C2420]">
                {feature.title}
              </h3>
              <p className="mt-4 text-[14px] leading-[1.8] text-[#8C7B70]">
                {feature.body}
              </p>

              {/* Detail strip */}
              <div className="mt-8 flex items-center gap-3">
                <span className="h-px w-6 bg-[#D4C9BB]" />
                <span className="text-[11px] tracking-[0.1em] uppercase text-[#A0907F]">
                  {feature.detail}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Bottom feature visual — waveform */}
        <div className="mt-16 border border-[#E8E2D9] p-10">
          <div className="flex items-center gap-4 mb-6">
            <span className="h-px w-8 bg-[#8C7B70]" />
            <p className="text-[11px] tracking-[0.22em] uppercase text-[#8C7B70]">
              Live Example
            </p>
          </div>
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:gap-12">
            <div className="flex-1">
              <h3 className="font-serif text-2xl text-[#2C2420] leading-snug">
                Voice agent call visualized in real time
              </h3>
              <p className="mt-3 text-[14px] leading-[1.75] text-[#8C7B70] max-w-sm">
                Every call is recorded, transcribed, and summarized — visible in your physician dashboard.
              </p>
            </div>

            {/* Waveform visual */}
            <div className="flex items-end gap-[3px]">
              {[14, 24, 10, 32, 20, 38, 18, 35, 12, 28, 22, 32, 16, 26, 20, 36, 14, 28, 18, 24, 30, 20, 36, 14, 32, 22, 28, 16, 34, 20].map(
                (h, i) => (
                  <div
                    key={i}
                    className="w-1.5 rounded-full bg-[#D4C9BB] hover:bg-[#2C2420] transition-colors duration-150"
                    style={{ height: `${h}px` }}
                  />
                )
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
