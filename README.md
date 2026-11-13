# Roblox Up-and-Coming Top-10 Forecaster

Forecasts Roblox's Up-and-Coming chart (top 10, place by place) for the
72 hours after entries close, for the make.fun bounty
`roblox-up-and-coming-forecast-01`.

## How it works

`main.py` (Python 3.12/3.13, standard library only, deterministic) reads
`$MAKEFUN_INPUT_DIR/history.ndjson` and `task.json`, then writes
`$MAKEFUN_OUTPUT_DIR/forecast.json`:

- Per game, a recency-weighted (12 h decay) place frequency and mean rank
  over the chart history.
- Player-count momentum: the log slope of `playing` over the last few
  reads shifts the game's expected rank up or down.
- Age-out: games leave the chart about 28 days after creation, so when
  `details.created` is present a game nearing that age is faded out.
- Per place, the probability blends the empirical place frequency with a
  Gaussian centred on the game's expected rank (sigma 5 places).
- Only 60% of each place's mass is named (top 40 candidates); the rest
  stays unnamed so games entering the chart mid-window still score far
  above the floor.

## Run

```sh
MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=<out dir> python3 main.py
```

## Backtest

Hold-out scoring inside the practice history (train before the cutoff,
score against later reads) beats the persistence baseline on every window
tested (about -44.4 vs about -53.0 mean log score; the house baseline
scores -43.51 on the practice window). Local scorer:
`~/workspace/makefun/roblox-dev/proto.py` (not part of this entry).
