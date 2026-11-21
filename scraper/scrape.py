import io, json, re, sys, time
from pathlib import Path
import pandas as pd
import requests

SEASON = "2026-27"
SR_YEAR = "20" + SEASON[-2:]
DATA = Path(__file__).resolve().parent.parent / "data"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IMG-Dashboard stats updater)"}
ALIASES = {
    "opp": ["Opp", "Opponent"], "result": ["Result", "Score", "W/L"],
    "mp": ["MP", "MIN", "Min"], "pts": ["PTS", "Pts"],
    "orb": ["ORB", "OFF", "OR", "Off"], "drb": ["DRB", "DEF", "DR", "Def"],
    "ast": ["AST", "A", "Ast"], "stl": ["STL", "ST", "Stl"], "tov": ["TOV", "TO", "Tov"],
    "fg": ["FG", "FGM"], "fga": ["FGA"], "fgm_fga": ["FGM-FGA", "FG-FGA"],
}
STATS = ["mp", "pts", "orb", "drb", "ast", "stl", "tov", "fg", "fga"]
SR_HOST = "sports-reference.com"
SR_DELAY = 65
OTHER_DELAY = 5


def game_log_url(url):
    m = re.match(r"(https://www\.sports-reference\.com/cbb/players/[\w-]+?)(?:\.html|/gamelog/\d{4})", url)
    return f"{m.group(1)}/gamelog/{SR_YEAR}" if m else url


def pick(cols, key):
    return next((c for c in ALIASES[key] if c in cols), None)


def num(v):
    v = str(v).split(":")[0]
    return int(float(v)) if re.fullmatch(r"-?\d+(\.\d+)?", v) else None


def parse(html):
    html = html.replace("<!--", "").replace("-->", "")
    for t in pd.read_html(io.StringIO(html)):
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = t.columns.get_level_values(-1)
        t.columns = [str(c).strip() for c in t.columns]
        if not (pick(t.columns, "pts") and pick(t.columns, "mp")):
            continue
        games = []
        for _, r in t.iterrows():
            g = {k: num(r[pick(t.columns, k)]) if pick(t.columns, k) else None for k in STATS}
            col = pick(t.columns, "fgm_fga")
            if col and "-" in str(r[col]):
                g["fg"], g["fga"] = (num(x) for x in str(r[col]).split("-")[:2])
            if g["mp"] is None or g["pts"] is None or g["mp"] == 0:
                continue
            opp = str(r[pick(t.columns, "opp")]).strip() if pick(t.columns, "opp") else ""
            if not opp or opp.lower() in ("nan", "total", "totals", "opp"):
                continue
            res = str(r[pick(t.columns, "result")]).strip() if pick(t.columns, "result") else None
            games.append({"opp": opp, "result": None if res in (None, "nan") else res,
                          **{k: g[k] or 0 for k in STATS}})
        if games:
            return games
    return []


def main():
    roster = json.loads((DATA / "roster.json").read_text())
    out_path = DATA / f"{SEASON}.json"
    old = json.loads(out_path.read_text()) if out_path.exists() else {"games": []}
    kept = {}
    for g in old["games"]:
        kept.setdefault(g["player_id"], []).append(g)

    games, report, last_sr, sr_blocked = [], [], 0, False
    for p in roster:
        s = p["seasons"].get(SEASON)
        name = f'{p["first"]} {p["last"]}'
        if not p["active"] or not s or not s.get("url"):
            report.append(f"skip   {name}: no {SEASON} link")
            continue
        url = game_log_url(s["url"])
        is_sr = SR_HOST in url
        if is_sr and sr_blocked:
            games += kept.get(p["id"], [])
            report.append(f"skip   {name}: Sports Reference rate-limited this run (kept old games)")
            continue
        if is_sr:
            time.sleep(max(0, SR_DELAY - (time.time() - last_sr)))
            last_sr = time.time()
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if is_sr and r.status_code == 429:
                sr_blocked = True
            r.raise_for_status()
            found = parse(r.text)
        except Exception as e:
            found, err = [], str(e)[:80]
        else:
            err = "no game table found"
        if found:
            games += [{"player_id": p["id"], "team": s["team"], "game": i, **g, "source": "scraper"}
                      for i, g in enumerate(found, 1)]
            report.append(f"ok     {name}: {len(found)} games, {sum(g['pts'] for g in found)} pts")
        else:
            games += kept.get(p["id"], [])
            report.append(f"FAIL   {name}: {err} (kept {len(kept.get(p['id'], []))} old games)")
        if not is_sr:
            time.sleep(OTHER_DELAY)

    out_path.write_text(json.dumps({"season": SEASON, "games": games}, indent=1))
    print("\n".join(report))
    print(f"\n{len(games)} games written to {out_path.name}")


if __name__ == "__main__":
    sys.exit(main())
