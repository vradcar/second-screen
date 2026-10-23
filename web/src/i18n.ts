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
    "Listening for the next big moment…": "Atentos a la próxima jugada…", "Tap for live commentary": "Toca para escuchar la narración",
    "Match centre": "Centro del partido", "Key events": "Momentos clave", "Substitutes": "Suplentes", "touches": "toques",
    "No goals, bookings or substitutions yet.": "Aún no hay goles, tarjetas ni cambios.",
    "Analyst hub": "Centro de análisis", "Match analysis": "Análisis del partido", "Attack": "Ataque",
    "Defence": "Defensa", "Match flow": "Desarrollo del partido", "Territory": "Territorio", "Passing network": "Red de pases", "Data to": "Datos hasta", "Waiting for kick-off…": "Esperando el inicio…",
    "Overview": "Resumen", "Line-ups": "Alineaciones", "Players": "Jugadores", "Shots": "Tiros", "Passing": "Pases",
    "Heatmaps": "Mapas de calor", "Physical": "Físico", "Team comparison": "Comparativa", "xG race": "Carrera de xG",
    "Possession": "Posesión", "Expected goals (xG)": "Goles esperados (xG)", "On target": "A puerta",
    "Big chances": "Ocasiones claras", "Passes": "Pases", "Pass accuracy": "Precisión de pase",
    "Progressive passes": "Pases progresivos", "Box entries": "Llegadas al área", "Field tilt": "Dominio territorial",
    "PPDA (lower = more pressing)": "PPDA (menos = más presión)", "High turnovers": "Recuperaciones altas",
    "Pressures": "Presiones", "Tackles won": "Entradas ganadas", "Interceptions": "Intercepciones", "Corners": "Córners",
    "Fouls": "Faltas", "Yellow cards": "Amarillas", "Red cards": "Rojas",
    "Cumulative expected goals: the quality of chances each side has created. Dots are goals.": "Goles esperados acumulados: la calidad de las ocasiones de cada equipo. Los puntos son goles.",
    "Both teams": "Ambos", "Player": "Jugador", "Click a column to sort.": "Pulsa una columna para ordenar.",
    "Min": "Min", "Touches": "Toques", "Acc.": "Prec.", "Prog.": "Prog.", "Key P.": "P. clave", "Drib.": "Regates",
    "Tkl": "Entr.", "Int.": "Int.", "Press.": "Pres.", "Top km/h": "Máx. km/h", "Shot map": "Mapa de tiros",
    "bigger = better chance": "más grande = mejor ocasión", "Saved": "Parado", "Blocked": "Bloqueado",
    "Off target": "Fuera", "Woodwork": "Palo", "Outcome": "Resultado", "Body part": "Parte del cuerpo", "Situation": "Situación",
    "Passing links on the team's shape: thicker lines = more passes between the pair, bigger circles = more passes played. Attacking left to right.": "Conexiones de pase sobre el dibujo del equipo: líneas más gruesas = más pases entre la pareja, círculos más grandes = más pases. Atacando de izquierda a derecha.",
    "Whole team": "Todo el equipo", "Where they had the ball. Attacking left to right.": "Dónde tuvieron el balón. Atacando de izquierda a derecha.",
    "Distance covered and top speed, from the tracking snapshots.": "Distancia recorrida y velocidad máxima, del tracking.",
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
    "Listening for the next big moment…": "À l'affût du prochain temps fort…", "Tap for live commentary": "Touchez pour le commentaire en direct",
    "Match centre": "Centre du match", "Key events": "Faits marquants", "Substitutes": "Remplaçants", "touches": "ballons",
    "No goals, bookings or substitutions yet.": "Pas encore de but, de carton ni de changement.",
    "Analyst hub": "Centre d'analyse", "Match analysis": "Analyse du match", "Attack": "Attaque",
    "Defence": "Défense", "Match flow": "Physionomie du match", "Territory": "Territoire", "Passing network": "Réseau de passes", "Data to": "Données à", "Waiting for kick-off…": "En attente du coup d'envoi…",
    "Overview": "Résumé", "Line-ups": "Compositions", "Players": "Joueurs", "Shots": "Tirs", "Passing": "Passes",
    "Heatmaps": "Cartes de chaleur", "Physical": "Physique", "Team comparison": "Comparaison", "xG race": "Course aux xG",
    "Possession": "Possession", "Expected goals (xG)": "Buts attendus (xG)", "On target": "Cadrés",
    "Big chances": "Grosses occasions", "Passes": "Passes", "Pass accuracy": "Précision des passes",
    "Progressive passes": "Passes progressives", "Box entries": "Entrées dans la surface", "Field tilt": "Domination territoriale",
    "PPDA (lower = more pressing)": "PPDA (plus bas = plus de pressing)", "High turnovers": "Récupérations hautes",
    "Pressures": "Pressions", "Tackles won": "Tacles réussis", "Interceptions": "Interceptions", "Corners": "Corners",
    "Fouls": "Fautes", "Yellow cards": "Cartons jaunes", "Red cards": "Cartons rouges",
    "Cumulative expected goals: the quality of chances each side has created. Dots are goals.": "Buts attendus cumulés : la qualité des occasions de chaque équipe. Les points sont les buts.",
    "Both teams": "Les deux", "Player": "Joueur", "Click a column to sort.": "Cliquez sur une colonne pour trier.",
    "Min": "Min", "Touches": "Ballons", "Acc.": "Préc.", "Prog.": "Prog.", "Key P.": "P. clés", "Drib.": "Dribbles",
    "Tkl": "Tacles", "Int.": "Int.", "Press.": "Press.", "Top km/h": "V. max", "Shot map": "Carte des tirs",
    "bigger = better chance": "plus gros = meilleure occasion", "Saved": "Arrêté", "Blocked": "Contré",
    "Off target": "Non cadré", "Woodwork": "Poteau", "Outcome": "Issue", "Body part": "Surface", "Situation": "Situation",
    "Passing links on the team's shape: thicker lines = more passes between the pair, bigger circles = more passes played. Attacking left to right.": "Liens de passes sur le schéma de l'équipe : traits plus épais = plus de passes entre les deux, cercles plus gros = plus de passes. Attaque de gauche à droite.",
    "Whole team": "Toute l'équipe", "Where they had the ball. Attacking left to right.": "Où ils ont eu le ballon. Attaque de gauche à droite.",
    "Distance covered and top speed, from the tracking snapshots.": "Distance parcourue et vitesse maximale, d'après le tracking.",
  },
};

export const isNative = (lang: string) => lang === "en" || lang in UI;
/** True when this label has a hand-written translation; anything else goes through the translator. */
export const hasLabel = (lang: string, template: string) => lang === "en" || template in (UI[lang] ?? {});

/** Fill a template in the viewer's language if it's native; else English (for translation). */
export function uiText(template: string, lang: string, vars: Record<string, string | number> = {}): string {
  const tpl = UI[lang]?.[template] ?? template;
  return tpl.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? ""));
}
