"""Roblox Up-and-Coming top-10 forecaster.

Reads $MAKEFUN_INPUT_DIR/history.ndjson (+ task.json) and writes
$MAKEFUN_OUTPUT_DIR/forecast.json: per-place probabilities for the chart's
top 10 places over the scored window, plus a best-guess top 10.

Model (pure stdlib, deterministic, no network):
  * For every game, a recency-weighted (12 h half-life style decay) place
    frequency over the history, and a recency-weighted mean rank.
  * Player-count momentum: the log slope of `playing` over the last few
    reads shifts the game's expected rank up (rising) or down (falling).
  * Age-out: games leave the chart about 28 days after creation, so when
    `details.created` is present a game nearing that age is faded out.
  * Per place, probability blends the empirical place frequency with a
    Gaussian centred on the game's expected rank (sigma 5 places).
  * Only 65% of each place's mass is named (top 40 candidates); the rest
    stays unnamed so games entering the chart mid-window still score
    far above the floor instead of ln(0.0001).

Run: python3 main.py
"""
import json
import math
import os
from datetime import datetime, timezone

TAU_H = 12.0        # recency decay horizon, hours
SIGMA = 5.0         # Gaussian width around expected rank, places
W_FREQ = 0.7        # weight of empirical place frequency
W_GAUSS = 0.3       # weight of Gaussian around expected rank
NAMED_SUM = 0.60    # share of each place's mass given to named games
TOP_N = 40          # candidates named per place (limit is 100)
MOM_W = 5.0         # momentum strength (rank places per log-playing/hour)
FLOOR_ADD = 0.002   # small mass so every chart game is named somewhere
MAX_RANK = 60       # ranks worse than this count as 60
CHART_MAX_AGE_DAYS = 28.0


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_history(input_dir):
    rows = []
    path = os.path.join(input_dir, "history.ndjson")
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["at"])
    return rows


def load_task(input_dir):
    path = os.path.join(input_dir, "task.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except OSError:
        return {}


def build_forecast(rows, window_from):
    t_last = parse_ts(rows[-1]["at"])
    games = {}
    created = {}
    for r in rows:
        t = parse_ts(r["at"])
        age_h = (t_last - t).total_seconds() / 3600.0
        w = math.exp(-age_h / TAU_H)
        for g in r.get("up_and_coming") or []:
            uid = g["universe_id"]
            d = games.setdefault(uid, {"freq": {}, "wsum": 0.0, "series": []})
            rank = g.get("rank")
            if rank is not None and rank <= 30:
                d["freq"][rank] = d["freq"].get(rank, 0.0) + w
            d["wsum"] += w
            playing = g.get("playing")
            d["series"].append((t, rank, playing))
        det = r.get("details") or {}
        for uid_s, info in det.items():
            if info and info.get("created"):
                try:
                    created[int(uid_s)] = parse_ts(info["created"])
                except (ValueError, TypeError):
                    pass

    exp_rank = {}
    age_factor = {}
    for uid, d in games.items():
        num = 0.0
        den = 0.0
        for (t, rank, _playing) in d["series"]:
            if rank is None:
                continue
            age_h = (t_last - t).total_seconds() / 3600.0
            w = math.exp(-age_h / TAU_H)
            num += w * min(rank, MAX_RANK)
            den += w
        er = num / den if den > 0 else float(MAX_RANK)
        s = d["series"][-5:]
        mom = 0.0
        if len(s) >= 2:
            p0 = s[0][2]
            p1 = s[-1][2]
            if p0 and p1 and p0 > 0 and p1 > 0:
                dt_h = (s[-1][0] - s[0][0]).total_seconds() / 3600.0
                if dt_h > 0:
                    mom = (math.log(p1) - math.log(p0)) / dt_h
        er = er - MOM_W * mom * 24.0
        exp_rank[uid] = max(1.0, min(float(MAX_RANK), er))
        f = 1.0
        if uid in created:
            age_days = (window_from - created[uid]).total_seconds() / 86400.0
            remaining = CHART_MAX_AGE_DAYS - age_days
            if remaining <= 0:
                f = 0.05
            elif remaining < 3.0:
                f = 0.2 + 0.8 * (remaining / 3.0)
        age_factor[uid] = f

    all_uids = sorted(games.keys())
    top10 = sorted(all_uids, key=lambda u: (exp_rank[u], u))[:10]
    probs = []
    for place in range(1, 11):
        raw = {}
        for uid in all_uids:
            d = games[uid]
            freq = d["freq"].get(place, 0.0) / d["wsum"] if d["wsum"] > 0 else 0.0
            gauss = math.exp(-((place - exp_rank[uid]) ** 2) / (2 * SIGMA * SIGMA))
            raw[uid] = (W_FREQ * freq + W_GAUSS * gauss) * age_factor[uid] + FLOOR_ADD
        cands = sorted(raw.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_N]
        tot = sum(v for _, v in cands)
        for uid, v in cands:
            probs.append({"universe_id": uid, "place": place,
                          "p": round(NAMED_SUM * v / tot, 6)})
    return {"probabilities": probs, "top10": top10}


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    rows = load_history(input_dir)
    task = load_task(input_dir)
    window = task.get("window") or {}
    if window.get("from"):
        window_from = parse_ts(window["from"])
    else:
        window_from = parse_ts(rows[-1]["at"])
    forecast = build_forecast(rows, window_from)
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "forecast.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(forecast, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")
    print("wrote %s (%d probability rows, top10 %s)"
          % (out_path, len(forecast["probabilities"]), forecast["top10"]))


if __name__ == "__main__":
    main()
