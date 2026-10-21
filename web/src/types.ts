export interface Player { player_id: string; name: string; number: number; position: string }
export interface Team {
  team_id: string; name: string; short_name: string; colors: [string, string];
  starting_xi: Player[]; bench: Player[];
}
export interface Meta {
  match_id: string; home: Team; away: Team; mode: string; speed: number;
  duration: number; start_elapsed: number;
}
export interface MatchEvent {
  event_id: string; seq: number; type: string; team_id?: string; player_id?: string; player_name?: string;
  x?: number; y?: number; end_x?: number; end_y?: number; outcome?: string; recipient_id?: string;
  elapsed_seconds: number; clock: string; period: number; distance_m?: number; ball_speed_kmh?: number;
  speed_kmh?: number; shot_speed_kmh?: number; score?: Record<string, number>; card?: string;
  player_off_id?: string; assist_name?: string; body_part?: string;
}
export interface StatChip { label: string; value: string }
export interface Cue {
  cue_id: string; moment_id: string | null; kind?: string; persona_id: string; lang: string; type: string;
  clock: string; elapsed: number; duration_s: number; priority: number;
  team_id: string | null; player_id: string | null;
  text: { strap: string; card: string | null }; stats: StatChip[]; evidence: string[];
}
export interface Claim { text: string; facts: string[] }
export interface Draft { headline: string; summary: string; why_it_matters: string; theme: string; claims: Claim[] }
export interface Rendering { persona_id: string; lang: string; lower_third: string; body: string; stat_chips: StatChip[] }
export interface Moment {
  moment_id: string; signal_id: string; kind: string; clock: string; minute: number; elapsed: number;
  team_id: string | null; player_id: string | null; importance: number; source: "agent" | "fallback";
  attempts: number; draft: Draft; renderings: Rendering[]; cues: Cue[]; evidence: string[];
  check_log: Record<string, unknown>[]; facts?: Record<string, unknown>; latency_s?: number;
}
export interface TeamSummary {
  team_id: string; name: string; goals: number; xg: number; shots: number; shots_on_target: number;
  big_chances: number; possession_pct: number; field_tilt_pct: number; passes: number;
  pass_completion: number | null; ppda: number | null; high_turnovers: number; pressures: number;
  box_entries: number; players_on_pitch: number; corners: number; fouls: number;
}
export interface SeriesPoint { minute: number; period: number; elapsed: number; momentum: number; regime: string; score: Record<string, number> }
export interface Snapshot {
  clock: string; period: number; score: Record<string, number>; teams: Record<string, TeamSummary>;
  momentum: number; regime: string; pressing: Record<string, { active: boolean; rate: number }>;
  series: SeriesPoint[];
  players: { player_id: string; name: string; team_id: string; goals: number; assists: number; xg: number;
             shots: number; touches: number; distance_m: number; top_speed_kmh: number; on_pitch: boolean }[];
}
export interface RecapDoc {
  recap: { title: string; standfirst: string; paragraphs: { text: string; moment_ids: string[] }[];
           player_of_the_match: string; player_of_the_match_reason: string };
  source: string;
}
export interface Persona { id: string; label: string; short: string; lang: string; accent: string; focus?: string; club?: string }
