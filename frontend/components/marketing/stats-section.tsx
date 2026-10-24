const stats = [
  {
    value: "< 5min",
    label: "From trigger fired to patient contacted",
    note: "Industry avg is 2–4 hours",
  },
  {
    value: "30%",
    label: "Reduction in no-show appointments",
    note: "Across all clinic types",
  },
  {
    value: "40%",
    label: "Less administrative workload per provider",
    note: "Measured at 12-month mark",
  },
  {
    value: "99.9%",
    label: "Platform uptime during clinic hours",
    note: "SLA-backed guarantee",
  },
];

export function StatsSection() {
  return (
    <section className="bg-[#F5F0E8] py-24 md:py-32">
      <div className="mx-auto max-w-7xl px-8">
        {/* Section label */}
        <div className="flex items-center gap-4 mb-16">
          <span className="h-px w-8 bg-[#8C7B70]" />
          <p className="text-[11px] tracking-[0.22em] uppercase text-[#8C7B70]">
            By the Numbers
          </p>
        </div>

        {/* Stats in row */}
        <div className="grid grid-cols-2 gap-0 border-l border-[#D4C9BB] lg:grid-cols-4">
          {stats.map((stat, i) => (
            <div
              key={stat.label}
              className={`border-r border-[#D4C9BB] px-8 py-8 ${
                i >= 2 ? "border-t border-[#D4C9BB]" : ""
              } lg:border-t-0`}
            >
              <p className="font-serif text-[clamp(2.4rem,5vw,3.8rem)] leading-none text-[#2C2420] tracking-tight">
                {stat.value}
              </p>
              <p className="mt-4 text-[13px] leading-[1.6] text-[#5C4D43]">
                {stat.label}
              </p>
              <p className="mt-3 text-[11px] tracking-[0.08em] uppercase text-[#A0907F]">
                {stat.note}
              </p>
            </div>
          ))}
        </div>

        {/* Quote */}
        <div className="mt-16 border-t border-[#D4C9BB] pt-12 flex gap-8 items-start">
          <span className="font-serif text-5xl leading-none text-[#D4C9BB] select-none">&ldquo;</span>
          <div>
            <p className="font-serif text-[1.25rem] leading-[1.55] text-[#2C2420] max-w-2xl italic">
              CareSync AI reduced our no-show rate by a third in the first ninety days.
              The AI calls are indistinguishable from a real coordinator.
            </p>
            <p className="mt-5 text-[12px] tracking-[0.1em] uppercase text-[#8C7B70]">
              Dr. Priya Mehta — Internal Medicine, Bengaluru
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
