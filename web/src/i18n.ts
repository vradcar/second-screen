/** The broadcast's own labels, native in English, Spanish and French. Other languages go through
 * Azure AI Translator (see useLiveTranslate). Keys are the English templates. */
const UI: Record<string, Record<string, string>> = {
  es: {
    "Pass": "Pase", "Carry": "Conducción", "Shot": "Disparo", "Beats his man": "Regate", "Interception": "Intercepción",
    "Tackle": "Entrada", "Clearance": "Despeje", "Save": "Parada", "Block": "Bloqueo", "Corner": "Córner",
    "Penalty": "Penalti", "On the ball": "Con el balón", "Goal": "Gol", "Red card": "Tarjeta roja",
    "Following": "Siguiendo", "out of play": "fuera", "intercepted": "interceptado",
    "Open, chaotic phase": "Fase abierta y caótica", "Even contest": "Partido igualado",
    "{name} is sent off": "{name}, expulsado", "{team} in control": "{team} domina", "{n}-pass move": "{n} pases seguidos",
    "Full-time report": "Crónica del partido", "Player of the match": "Jugador del partido",
    "Commentator": "Narrador", "Co-commentator": "Comentarista", "Commentary box": "Cabina de comentarios",
    "Listening for the next big moment…": "Atentos a la próxima jugada…",
  },
  fr: {
    "Pass": "Passe", "Carry": "Percée", "Shot": "Frappe", "Beats his man": "Dribble", "Interception": "Interception",
    "Tackle": "Tacle", "Clearance": "Dégagement", "Save": "Arrêt", "Block": "Contre", "Corner": "Corner",
    "Penalty": "Penalty", "On the ball": "Au ballon", "Goal": "But", "Red card": "Carton rouge",
    "Following": "Suivi", "out of play": "sortie", "intercepted": "interceptée",
    "Open, chaotic phase": "Phase ouverte et décousue", "Even contest": "Match équilibré",
    "{name} is sent off": "{name} est exclu", "{team} in control": "{team} contrôle le jeu",
    "{n}-pass move": "{n} passes d'affilée", "Full-time report": "Le résumé du match", "Player of the match": "Homme du match",
    "Commentator": "Commentateur", "Co-commentator": "Consultant", "Commentary box": "Cabine de commentaire",
    "Listening for the next big moment…": "À l'affût du prochain temps fort…",
  },
};

export const isNative = (lang: string) => lang === "en" || lang in UI;

/** Fill a template in the viewer's language if it's native; else English (for translation). */
export function uiText(template: string, lang: string, vars: Record<string, string | number> = {}): string {
  const tpl = UI[lang]?.[template] ?? template;
  return tpl.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
}
