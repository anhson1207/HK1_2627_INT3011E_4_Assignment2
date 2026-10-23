"""Allow ``python -m bmp`` to invoke the command-line interface."""

from bmp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
