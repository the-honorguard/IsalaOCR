from __future__ import annotations

import argparse

from .labeler import serve_labeler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local IsalaOCR exact-label interface."
    )
    parser.add_argument("--workspace", default="/training/workspace")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    serve_labeler(args.workspace, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
