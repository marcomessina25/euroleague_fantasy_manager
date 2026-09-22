"""CLI script wrapper for importing a 11-unit EuroLeague Fantasy squad from players.txt."""

from euroleague_fantasy_manager.import_squad import import_squad_from_file


def main() -> None:
    import_squad_from_file()


if __name__ == "__main__":
    main()
