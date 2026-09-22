# EuroLeague Fantasy Manager architecture

> **Living document.** This defines the project's purpose, architectural boundaries, and non-negotiable responsibilities. Human contributors and AI agents must read it before material design or implementation work and update it when these decisions change.

## Purpose

EuroLeague Fantasy Manager (`elf`) is a local-first decision-support system for **EuroLeague Fantasy Challenge (Classic Mode)**, beginning with the 2026/27 season (`E2026`, `league_id=10`), and architected to share its full data model, rules engine, and API clients with **EuroCup Fantasy Challenge** (`U2026`, `league_id=11`).

Its aim is to support a serious human + quantitative model + LLM workflow while preventing the rule, budget, price, formation, and turn-lockout mistakes that a general-purpose LLM can make.

It is **not** an autonomous team manager. A human remains responsible for final EuroLeague Fantasy decisions, intra-round turn substitutions (`T1 -> T2`), and trade execution.

## Core principles

- Deterministic software is the source of truth for EuroLeague Fantasy facts, rules, budget, capital gains (`0%` sell-on tax), 11-unit squad state (`4G, 4F, 2C, 1HC`), formations (`2-2-1`, `1-2-2`, `2-1-2`, `1-3-1`, `3-1-1`), and turn lockouts (`T1`, `T2`, `T3`).
- Every recommendation must pass an independent validator before it is shown as actionable.
- Quantitative projections estimate expected value ($\text{xPDK}$), expected capital variation ($\Delta \text{Cr}$), and Turn-1 to Turn-2 real option value ($\Delta \text{Option xP}$); they do not invent facts.
- Multi-competition inheritance: `league_id` (`10` = EuroLeague, `11` = EuroCup) and `competition_code` (`"E"` = EuroLeague, `"U"` = EuroCup) are parameterized at the transport and storage layers so EuroCup can inherit the entire stack seamlessly.
- LLMs are strategic analysts over structured, generated data. They are not the optimizer or source of truth.
- Decisions, intra-round substitutions, alternatives, and outcomes should be recorded so the system can be evaluated and improved.
- The system runs locally with zero external runtime dependencies (`urllib.request` + `sqlite3`) except for public data downloads and optional LLM API calls.

## Planned architecture

```text
Official EuroLeague Fantasy API          Official EuroLeague Feeds API
(fantaking-api.dunkest.com/api/v1)      (feeds.incrowdsports.com/v2)
prices, turns, lineups, coaches         clubs, calendar, PIR box scores
            |                                         |
            +------------> local SQLite data <--------+
                                  |
                     +------------+------------+
                     |                         |
              Quantitative model          ELF optimizer
           xPDK, coach win-margins,    legal 11-unit squads, 1..4 trades,
           capital gain (dCr), xM      T1/T2 option-value lineup & captain
                     |                         |
                     +------------+------------+
                                  |
                        Generated reports / facts
                                  |
                           LLM analysis layer
                      challenge assumptions, identify
                      uncertainty and strategic trade-offs
                                  |
                             Human decision
                                  |
                        Decision and outcome log
```

## Responsibilities by layer

| Layer | Responsibility | Must not do |
| --- | --- | --- |
| Fantasy & EuroLeague ingestion + database | Fetch and persist official snapshots, current prices (`quotation`), coaches, turns (`T1/T2/T3`), lineups, and gameweek facts | Make recommendations |
| Rules + validator | Enforce `100.0 Cr` + capital-gain budget, `4G/4F/2C/1HC` quotas, club limit (`<= 6`), 5 court formations, `1.0x`/`0.5x`/`2.0x` scoring weights, `<= 4` trades/round, and Unlimited Trade Windows | Trust LLM output without validation |
| Quant model | Estimate player PIR + 10% win bonus ($\text{xPDK}$), coach margin points, minutes ($\text{xM}$), and credit changes ($\Delta \text{Cr}$) | Override hard EuroLeague Fantasy facts |
| Optimizer | Search legal 11-unit squads, `1..4` trades, Unlimited Window overhauls, and `T1/T2` option-aware starting 5 + 6th man + captain | Reason from unstructured news alone |
| LLM analyst | Interpret generated facts, expose assumptions, and suggest strategic deviations | Invent data or bypass validation |
| Human | Make final choices, execute trades, and perform `T1 -> T2` substitutions | Treat a model recommendation as guaranteed |
