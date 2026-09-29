# Automatic Squad Import Utility (`elf import-squad`)

Instead of manually looking up 11 integer player/coach IDs and editing `config/current_squad.json`, you can list your 10 players and 1 Head Coach in a plain-text `players.txt` file in the repository root (one name per line) and run:

```powershell
elf import-squad
```

or directly via Python:

```powershell
python scripts/import_squad.py
```

## Format of `players.txt`

Create `players.txt` in the project root (`c:\Projects\euroleague_fantasy_manager\players.txt`). Lines starting with `#` and blank lines are ignored. List your **4 Guards, 4 Forwards, 2 Centers, and 1 Head Coach**:

```text
# Guards (4)
Mike James
TJ Shorts
Sylvain Francisco
Facundo Campazzo

# Forwards (4)
Sasha Vezenkov
Chima Moneke
Tornike Shengelia
Alberto Abalde

# Centers (2)
Nikola Milutinov
Vincent Poirier

# Head Coach (1)
Georgios Bartzokas
```

## How It Works

1. Queries the latest local SQLite snapshot (`data/euroleague.sqlite3`) saved by `elf update`, scoped strictly to the target league (`--league eurocup` [id=11] or `--league euroleague` [id=10], defaulting to active team's league or EuroLeague).
2. Matches each line against full names or unique substrings across players and Head Coaches within that league's snapshot only (never cross-matching across competitions).
3. Prints status declarations for each entry:
   - `importing id <id> player <name> pos <position> team <team> price <credits>Cr (league <league_id>)`
   - `failed importing player <query> (league <league_id>)` (if no match or ambiguous match)
4. Writes the resolved IDs, current `price_tenths` (`quotation * 10`), and `league_id` into `config/current_squad.json`.
5. Validates against cross-league imports: attempting to import against an existing squad file from a different league raises an explicit league mismatch error.

## EuroCup Import Example

To import a EuroCup squad into `current_squad.json`:

```powershell
elf import-squad --league eurocup --file eurocup_players.txt --squad config/current_squad_ec.json
```

Or when an active EuroCup team is selected (`elf team select --id my_ec_team`), simply run:

```powershell
elf import-squad
```
