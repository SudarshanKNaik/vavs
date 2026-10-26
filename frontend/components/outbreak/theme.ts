import type { OutbreakLevel, SyndromeKey } from "@/services/api";

// Categorical slots 1-3 for the watched syndromes (validated against the app
// surface); "fever, unspecified" is folded into a neutral "other" grey.
export const SYNDROME_COLORS: Record<SyndromeKey, string> = {
  dengue_like: "#2a78d6",
  respiratory: "#eb6834",
  gastro: "#1baf7a",
  fever: "#A0907F",
};

export const SYNDROME_SHORT: Record<SyndromeKey, string> = {
  dengue_like: "Dengue-like",
  respiratory: "Respiratory",
  gastro: "Gastro",
  fever: "Fever only",
};

// Reserved status colours. Always shown with an icon and a label.
export const LEVELS: Record<OutbreakLevel, { label: string; color: string; tint: string; text: string }> = {
  alert: { label: "Alert", color: "#d03b3b", tint: "bg-[#d03b3b]/10 border-[#d03b3b]/30", text: "text-[#b42f2f]" },
  watch: { label: "Watch", color: "#fab219", tint: "bg-[#fab219]/15 border-[#fab219]/40", text: "text-[#8a5a00]" },
  normal: { label: "Normal", color: "#B8A898", tint: "bg-muted border-border", text: "text-muted-foreground" },
};
