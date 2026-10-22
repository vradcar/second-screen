import type { Persona } from "./types";

export const PERSONAS: Persona[] = [
  { id: "studio_analyst", label: "Studio analyst · English", short: "Analyst", lang: "en", accent: "#16202E" },
  { id: "halcyon_fan", label: "Halcyon City fan · English", short: "Halcyon fan", lang: "en", accent: "#1F4E8C", club: "HAL" },
  { id: "redmarsh_fan_es", label: "Redmarsh Rovers fan · Spanish", short: "Redmarsh (ES)", lang: "es", accent: "#B3261E", club: "RED" },
  { id: "lazaro_cam_fr", label: "Player cam: Ezra Lazaro · French", short: "Lazaro cam (FR)", lang: "fr", accent: "#9A7414", focus: "Ezra Lazaro" },
];

const KIND: Record<string, Record<string, string>> = {
  en: { goal: "Goal", red_card: "Red card", penalty_awarded: "Penalty", big_save: "Big save", big_chance_missed: "Big chance",
        pressing_spell: "Pressing", momentum_swing: "Momentum", regime_change: "Game state", hot_streak: "On fire",
        fatigue_fade: "Fatigue", late_surge: "Late surge", speed_alert: "Top speed", shot_speed: "Shot speed",
        yellow_card: "Booking", substitution: "Substitution", distance_milestone: "Distance", elite_pass: "Pass of the game" },
  es: { goal: "Gol", red_card: "Roja", penalty_awarded: "Penalti", big_save: "Paradón", big_chance_missed: "Ocasión",
        pressing_spell: "Presión", momentum_swing: "Inercia", regime_change: "Dinámica", hot_streak: "Inspirado",
        fatigue_fade: "Cansancio", late_surge: "Asedio final", speed_alert: "Velocidad", shot_speed: "Disparo",
        yellow_card: "Amarilla", substitution: "Cambio", distance_milestone: "Distancia", elite_pass: "Pase" },
  fr: { goal: "But", red_card: "Carton rouge", penalty_awarded: "Penalty", big_save: "Arrêt décisif", big_chance_missed: "Occasion",
        pressing_spell: "Pressing", momentum_swing: "Dynamique", regime_change: "Physionomie", hot_streak: "En feu",
        fatigue_fade: "Fatigue", late_surge: "Pression finale", speed_alert: "Vitesse", shot_speed: "Frappe",
        yellow_card: "Carton jaune", substitution: "Changement", distance_milestone: "Distance", elite_pass: "Passe" },
};

const CHECK: Record<string, [string, string, string]> = {
  en: ["Fact-checked", "Revised after fact-check", "Safe template (agent draft rejected)"],
  es: ["Verificado", "Corregido tras verificación", "Plantilla segura"],
  fr: ["Vérifié", "Corrigé après vérification", "Modèle sûr"],
};

export function kindLabel(kind: string, lang: string) {
  return (KIND[lang] ?? KIND.en)[kind] ?? kind.replace(/_/g, " ");
}

export function checkLabel(source: string, attempts: number, lang: string) {
  const c = CHECK[lang] ?? CHECK.en;
  return source === "fallback" ? c[2] : attempts > 1 ? c[1] : c[0];
}

/** Which instant signal a cue came from, from its id: "<match>-S0004-<persona>". */
export function cueKind(cueType: string, strap: string, stats: { label: string }[]) {
  const label = stats[0]?.label?.toLowerCase() ?? "";
  if (cueType === "lower_third" && strap.includes("·")) return "substitution";
  if (label.includes("speed") || label.includes("velocidad punta") || label.includes("vitesse de pointe")) return label.includes("shot") || label.includes("disparo") || label.includes("frappe") ? "shot_speed" : "speed_alert";
  if (label.includes("disparo") || label.includes("frappe")) return "shot_speed";
  if (label.includes("distan")) return "distance_milestone";
  if (label.includes("pass") || label.includes("pase") || label.includes("passe")) return "elite_pass";
  if (label.includes("yellow") || label.includes("amarilla") || label.includes("jaune")) return "yellow_card";
  return "speed_alert";
}

/** Hide chips that only make sense inside the engine (momentum scores, the score line). */
export function usefulChips<T extends { label: string; value: string }>(chips: T[]): T[] {
  return chips.filter((c) => !/momentum|score|marcador|inercia|dynamique|minutes? left|restantes|restantes/i.test(c.label)).slice(0, 3);
}
