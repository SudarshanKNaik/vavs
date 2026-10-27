'use client';

/** True for steps the AI builder drafted with no matching automation. */
export function isCustomNodeType(nodeType?: string) {
  return !!nodeType?.startsWith('custom_');
}

export function CustomTag() {
  return (
    <span
      title="No automation exists for this step yet. It's skipped when the workflow runs."
      className="ml-auto rounded-full border border-dashed border-current px-1.5 py-px text-[9px] font-semibold uppercase tracking-wider text-muted-foreground"
    >
      Custom
    </span>
  );
}
