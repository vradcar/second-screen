import type { KeyEvent, Meta, SheetPlayer, Snapshot, Team } from "./types";

type Ui = (t: string, vars?: Record<string, string | number>) => string;
const sur = (n: string) => n.split(" ").slice(-1)[0];

function Card({ red }: { red?: boolean }) {
  return <i className={`mc-card ${red ? "mc-red" : "mc-yellow"}`} aria-label={red ? "red card" : "yellow card"} />;
}

/** Team sheets and the key events: line-ups, goals, bookings and substitutions as they happen. */
export function MatchCentre({ snap, meta, ui, sheetsOnly }: { snap?: Snapshot; meta: Meta; ui: Ui; sheetsOnly?: boolean }) {
  const events = snap?.key_events ?? [];
  return (
    <section className="match-centre" aria-label={ui("Match centre")}>
      {!sheetsOnly && <h2 className="mc-title">{ui("Match centre")}</h2>}
      {!sheetsOnly && <Events events={events} meta={meta} ui={ui} />}
      <div className="mc-teams">
        {[meta.home, meta.away].map((t) => <Sheet key={t.team_id} team={t} rows={snap?.sheet?.[t.team_id] ?? []}
                                                  events={events.filter((e) => e.team_id === t.team_id)} ui={ui} />)}
      </div>
    </section>
  );
}

function Events({ events, meta, ui }: { events: KeyEvent[]; meta: Meta; ui: Ui }) {
  return (
    <ol className="mc-events" aria-label={ui("Key events")}>
      {events.length === 0 && <li className="mc-none">{ui("No goals, bookings or substitutions yet.")}</li>}
      {events.map((e, i) => <EventRow key={i} e={e} meta={meta} />)}
    </ol>
  );
}
MatchCentre.Events = Events;

function EventRow({ e, meta }: { e: KeyEvent; meta: Meta }) {
  const team = e.team_id === meta.away.team_id ? meta.away : meta.home;
  return (
    <li className={`mc-ev mc-ev-${e.kind}`} style={{ ["--team" as string]: team.colors[0] }}>
      <span className="mc-ev-clock">{e.clock}</span>
      <span className="mc-ev-icon" aria-hidden="true">
        {e.kind === "goal" ? "⚽" : e.kind === "sub" ? "⇄" : <Card red={e.kind === "red"} />}
      </span>
      <span className="mc-ev-text">
        {e.kind === "sub" ? <><b>{sur(e.player)}</b> <span className="mc-dim">for {sur(e.off ?? "")}</span></>
          : <><b>{sur(e.player)}</b>{e.kind === "goal" && e.assist && <span className="mc-dim"> (assist {sur(e.assist)})</span>}</>}
      </span>
      <span className="mc-ev-team">{team.short_name}</span>
    </li>
  );
}

function Sheet({ team, rows, events, ui }: { team: Team; rows: SheetPlayer[]; events: KeyEvent[]; ui: Ui }) {
  const byId = new Map(rows.map((r) => [r.player_id, r]));
  const xi = team.starting_xi.map((p) => byId.get(p.player_id) ?? { ...p, on_pitch: true } as unknown as SheetPlayer);
  const cameOn = new Set(events.filter((e) => e.kind === "sub").map((e) => e.player_id));
  const subs = team.bench.map((p) => byId.get(p.player_id) ?? ({ ...p, on_pitch: false } as unknown as SheetPlayer));
  const marks = (pid: string) => {
    const mine = events.filter((e) => e.player_id === pid || e.off_id === pid);
    return mine.map((e, i) => (
      <span key={i} className="mc-mark" title={e.clock}>
        {e.kind === "goal" && e.player_id === pid ? "⚽" : e.kind === "yellow" ? <Card /> : e.kind === "red" ? <Card red />
          : e.kind === "sub" ? <span className={e.player_id === pid ? "mc-on" : "mc-off"}>{e.player_id === pid ? "▲" : "▼"}</span> : null}
        <small>{e.clock.replace(/:\d\d$/, "'")}</small>
      </span>
    ));
  };
  const row = (p: SheetPlayer) => (
    <li key={p.player_id} className={`mc-p ${p.red ? "mc-sent-off" : ""} ${!p.on_pitch && !p.red ? "mc-off-pitch" : ""}`}>
      <span className="mc-num">{p.number}</span>
      <span className="mc-name">{p.name}<span className="mc-pos">{p.position}</span></span>
      <span className="mc-marks">{marks(p.player_id)}</span>
      <span className="mc-stats" title={`${p.touches} touches · ${p.passes} passes · ${p.km} km`}>
        {p.touches ? <>{p.touches}<small> {ui("touches")}</small> · {p.km}<small> km</small></> : <small>–</small>}
      </span>
    </li>
  );
  return (
    <div className="mc-team" style={{ ["--team" as string]: team.colors[0], ["--team2" as string]: team.colors[1] }}>
      <h3 className="mc-team-name">{team.name}</h3>
      <ol className="mc-xi">{xi.map(row)}</ol>
      <h4 className="mc-subs-title">{ui("Substitutes")}</h4>
      <ol className="mc-xi mc-bench">{subs.filter((p) => cameOn.has(p.player_id)).concat(subs.filter((p) => !cameOn.has(p.player_id))).map(row)}</ol>
    </div>
  );
}
