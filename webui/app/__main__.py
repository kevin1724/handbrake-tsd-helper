"""
Entry point for running the HandBrake TSD Helper Web UI as:

    python -m webui

This just:
- Creates the Flask app using the factory in __init__.py
- Starts the dev server (inside Docker you'll normally rely on gunicorn
  or just `python -m webui` as the container CMD).
"""

import argparse
import time

from . import create_app
from .node_linking import create_pairing_code


def _print_pairing_code(ttl_seconds: int) -> None:
    pairing = create_pairing_code(ttl_seconds=ttl_seconds)
    expires_at = time.strftime(
        "%Y-%m-%d %H:%M:%S %Z",
        time.localtime(float(pairing.get("expires_at") or 0)),
    )
    print(f"Pairing code: {pairing.get('code') or ''}", flush=True)
    print(f"Expires: {expires_at}", flush=True)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="ByteSqueeze controller tools")
    subcommands = parser.add_subparsers(dest="command")
    pairing_parser = subcommands.add_parser(
        "pairing-code",
        help="generate a new one-time node pairing code",
    )
    pairing_parser.add_argument("--ttl-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    if args.command == "pairing-code":
        _print_pairing_code(max(60, min(3600, int(args.ttl_seconds or 900))))
        return 0

    # Create the Flask app
    app = create_app()

    # Run the built-in Flask server
    # In Docker you'll expose port 8080 → 8080
    app.run(host="0.0.0.0", port=8080)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
