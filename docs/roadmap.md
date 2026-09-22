# EuroLeague Fantasy Manager roadmap

> **Living document.** This is the source of truth for delivery status, engineering priorities, release criteria, known risks, and long-term direction. Human contributors and AI agents must read it before material work and update it when priorities or milestone status changes.
>
> **Current planning baseline:** V0.1 foundation is completed on `main`. V0.2 implementation plan is on branch `v02` ([`docs/v02/v02.md`](v02/v02.md)).
>
> See [`docs/architecture.md`](architecture.md), [`docs/v02/v02.md`](v02/v02.md), and [`docs/squad_import.md`](squad_import.md) for architecture, V0.2 design, and workflow details.

---

## 0. Executive roadmap

The project is evolving from a deterministic EuroLeague Fantasy calculation engine into a complete **EuroLeague (and future EuroCup) Fantasy Challenge decision-support and experimentation platform**.

The system is built to answer:

- What should I do this Round (before Turn 1 lock)?
- What are the best legal `1..4` trade alternatives (including Head Coach swaps)?
- How should I partition my 11-unit squad (`5 Starters @ 1.0x`, `Captain @ 2.0x`, `6th Man @ 1.0x`, `4 Bench @ 0.5x`, `Head Coach @ 1.0x`) across **Turn 1 (`T1`)** and **Turn 2 (`T2`)** to maximize Real Option Value?
- Between Turn 1 and Turn 2, which realized `T1` scores should I sub out to the `0.5x` bench, and should I switch my `2.0x` Captain to an unplayed `T2` player?
- Which undervalued players will generate the highest **Capital Gain ($\Delta \text{Cr}$)** (with `0%` sell-on tax) to expand team budget above `100.0 Cr`?
- How should I prepare for the **6 Regular Season Unlimited Trade Windows** (`after R6, R13, R18, R23, R28, R34`)?
- How does ownership (`popularity`) affect template Shield vs differential Sword exposure?
- How did the recommendation perform against the human manager's actual decisions?

The core design principle remains:

```text
Official EuroLeague Fantasy + EuroLeague Feeds data
        ↓
Local point-in-time SQLite snapshots
        ↓
Deterministic Classic Mode rules / state
        ↓
Quantitative projections (xPDK, Coach margins, dCr)
        ↓
Optimizers / Turn-Option planners
        ↓
Strategic risk & ownership analysis
        ↓
Structured manager dossier
        ↓
Optional LLM qualitative analysis
        ↓
Deterministic validation
        ↓
Human decision (Pre-Round & Intra-Round T1->T2)
        ↓
Decision log
        ↓
Actual outcome
        ↓
Evaluation / backtesting
        ↓
Model improvement
```

---

# Delivery phases

## V0.1 — Trustworthy EuroLeague Fantasy data and rules foundation

**Status: completed on 2026-09-22.**

### Scope

- Download live EuroLeague Fantasy Challenge (`fantaking-api.dunkest.com/api/v1`, `league_id=10`) config, matchday/turn schedules (`T1/T2/T3`), and all 20 teams' match lineups (`350+` players and `20` Head Coaches with live `quotation` credits, positions, starter/bench/out statuses, and playing probabilities), alongside official EuroLeague (`feeds.incrowdsports.com/provider/euroleague-feeds/v2`, `E2026`) club metadata.
- Parameterize `league_id` (`10` = EuroLeague, `11` = EuroCup) and `competition_code` (`"E"` / `"U"`) so EuroCup can inherit the exact same pipeline later.
- Preserve timestamped raw JSON payloads under `data/raw/`.
- Normalize data into local SQLite snapshots (`data/euroleague.sqlite3`).
- Represent 11-unit rosters (`4 Guards, 4 Forwards, 2 Centers, 1 Head Coach`) and validate against `100.0 Cr` budget and `<= 6` club limit.
- Validate legal court lineups across all 5 basketball formations (`2-2-1`, `1-2-2`, `2-1-2`, `1-3-1`, `3-1-1`), Captain (`2.0x`), Sixth Man (`1.0x`), 4 Bench (`0.5x`), and Head Coach (`1.0x`).
- Establish deterministic trade validation (`1..4` trades per Round, 100% full selling price / zero sell-on tax, Head Coach trade counting toward the 4-trade limit, and Unlimited Trade Windows).
- Keep private squad configuration (`config/current_squad.json` and `players.txt`) out of Git.

### Completed

- Python 3.12 package scaffold (`euroleague_fantasy_manager`) and `elf` CLI entrypoint.
- `elf update` and `elf report`.
- Local SQLite `SnapshotStore` and raw-data archive.
- Deterministic squad (`11` units: `4G, 4F, 2C, 1HC`), court formation (`2-2-1`, `1-2-2`, `2-1-2`, `1-3-1`, `3-1-1`), and weighted-slot validation.
- Private Git-ignored `config/current_squad.json` format and `config/current_squad.example.json` template.
- Deterministic trade validation (`elf validate-trades`) with integer IDs, name resolution (`-n` / `--by-name`), and Unlimited Trade Window support (`--unlimited`).
- Squad import utility (`scripts/import_squad.py` and `elf import-squad`).
- Hermetic `pytest` suite covering rules, formations, trades, capital-gain selling prices, and SQLite snapshot persistence.

---

## V0.2 — Decision-support basics, Matchup FDR, xP baseline & Turn-aware Lineup

**Status: planned on branch `v02` ([`docs/v02/v02.md`](v02/v02.md)).**

### Scope

- Detailed current-squad reporting (`elf squad`): purchase prices, current `quotation` credits, realized/unrealized capital gains (`total_plus`), bank, total team value, and remaining trades (`0..4`).
- Multi-round fixture and Turn (`T1`/`T2`) schedule ticker (`elf fixtures --rounds 5`, `--squad-only`) with opponent defensive difficulty (FDR) by position (`G`, `F`, `C`, `HC`).
- Baseline Expected Fantasy Points ($\text{xPDK}$) model for players (modified PIR + 10% win bonus) and Head Coaches (`+10/+20/+25` win margins vs `-5/-10/-20` loss margins).
- **Turn-Aware Lineup & Captaincy Optimizer (`elf lineup`)**:
  - Optimizes Starting 5 (`1.0x`), Captain (`2.0x`), Sixth Man (`1.0x`), and 4 Bench (`0.5x`) while explicitly computing the **Turn 1 $\to$ Turn 2 Real Option Value** ($\mathbb{E}[\max(S_{T1}, S_{T2})]$) for starting `T1` players when `T2` backups exist on the bench.
- Automated `1..4` trade candidate generator and recommender (`elf suggest-trades --trades 1..4`).

---

## V0.3 — Component projections, Capital Gain model, Branch-and-Bound & Multi-Round Planner

**Status: planned.**

### Scope

- Expanded player & team stats ingestion from Dunkest (`api/stats/table`, `api/player/games`) and EuroLeague Feeds (`E2026` box scores).
- Component-based $\text{xPDK}$ & Expected Minutes ($\text{xM}$):
  - Starter probability, expected minutes, usage rate, scoring, rebounding, playmaking, stocks (`STL`/`BLK`), foul-drawing differential (`FD - PF`), shooting efficiency penalty (missed FG/FT), and team win probability.
  - Risk profiles: `neutral`, `floor`, `ceiling`, `defend_lead`, `chase`.
- **Expected Capital Gain ($\Delta \text{Cr}$) Model**:
  - Predicts post-round price variation as a function of $(\text{xPDK}, \text{current Cr})$ to optimize budget growth (`0%` sell-on tax).
- **Branch-and-Bound Trade Solver (`elf suggest-trades --trades 1..4`)** & **Unlimited Window Solver (`elf unlimited-trades`)**.
- **Multi-Round Rolling Planner (`elf plan --horizon 4`)** across single- and double-round EuroLeague weeks and approaching Unlimited Trade Windows.

---

## V0.4 — Intra-Turn live sub optimizer, Evaluation, Audit Trail & Ownership Risk

**Status: planned.**

### Scope

- **Between-Turn Substitution & Captaincy Switch Optimizer (`elf turn-subs`)**:
  - Given realized `T1` points and unplayed `T2`/`T3` bench players, computes exact optimal field-bench swaps, legal formation transitions, and Captain (`2.0x`) switches.
- Pre-round and intra-round decision logging (`elf log-decision`, `elf decisions`).
- Official live/post-round score ingestion (`elf update-scores`) and closed-loop evaluation (`elf evaluate`: MAE, RMSE, Spearman rank correlation, Captaincy regret, 6th-Man/Bench regret, and `T1->T2` Turn-Sub regret).
- Effective Ownership (`popularity`) & Strategic Risk (`elf ownership`, `elf risk`): `SHIELD`, `SWORD`, and `CORE` classification.
- Unlimited Trade Window calendar strategy (`elf window-strategy`) targeting `R6, R13, R18, R23, R28, R34`.

---

## V0.5 — Multi-team management and Basketball Court Web GUI

**Status: planned.**

### Scope

- **Multi-Team Management (`elf teams`, `elf team create/switch/clone/delete`)**:
  - Supports managing up to 3 isolated Classic Mode fantasy teams per account (`default`, differential, budget-builder) with team-scoped `squad.json` and decision logs.
- **Interactive Local Web Dashboard (`elf gui`)**:
  - Zero-dependency local web app featuring an interactive **Basketball Half-Court** (`5 Starters` + `Captain 2x` + `Head Coach` + `6th Man 1.0x` + `4 Bench 0.5x`), `T1 / T2 / T3` turn badges, Between-Turn Sub Simulator, Trade Studio, Unlimited Window Builder, Multi-Round Planner, and Evaluation Hub.

---

## V0.6+ — Future horizon (Live Turn Tracker, LLM Dossier, Historical Backtesting & EuroCup Inheritance)

**Status: future horizon.**

- **V0.6**: Analytical Manager Briefing, Live Matchday/Turn PIR & Credit Tracker, and Optional Multi-Provider LLM Strategy Critique (`elf advise`).
- **V0.7**: Multi-season (`2022/23–2025/26`) historical game-log acquisition (`api/player/games`), participation/foul-trouble calibration, and sequential decision A/B backtesting (`elf backtest-decisions`).
- **V0.8+**: Double-week turnaround congestion models, `With/Without Teammate` injury boost integration (`api/player/wo`), and **EuroCup Fantasy Challenge (`--league eurocup`, `league_id=11`, `competition_code="U"`)** activation using the shared architecture.
