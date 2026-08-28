"""`python3 -m workflow_spec.cli serve` — a real entry point, so a service unit need not embed
a snippet of Python in its ExecStart.

⚠️ `serve` refuses a non-localhost bind with no token; that check lives in `serve.serve()` and is
not repeated here, so there is one place it can be got wrong.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="workflow-spec")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the report viewer")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8800)

    args = ap.parse_args(argv)
    if args.cmd == "serve":
        from workflow_spec.serve import serve

        serve(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
