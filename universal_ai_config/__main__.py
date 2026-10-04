"""Allow running as `python -m universal_ai_config` and serve as the PyInstaller entry."""

from universal_ai_config.cli import main

if __name__ == "__main__":
    main()
