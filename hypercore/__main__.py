"""Module entrypoint for HyperCore."""

import argparse
import asyncio
import sys
import traceback

from hypercore.core.config import CORE_DEBUG
from hypercore.core.env_loader import project_root
from hypercore.core.health import run_health_check
from hypercore.core.kernel import HyperCoreKernel


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hypercore")
    parser.add_argument(
        "--runtime",
        choices=("both", "bot", "userbot"),
        default="both",
        help="Select which Telegram runtime to start.",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Run the credential-free HyperCore health check.",
    )
    return parser


async def _run(runtime_mode: str) -> int:
    kernel = HyperCoreKernel(runtime_mode=runtime_mode)
    return await kernel.run()


async def _run_health() -> int:
    report = await run_health_check(project_root())
    print(report.render())
    return report.exit_code


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.health:
            return asyncio.run(_run_health())
        return asyncio.run(_run(args.runtime))
    except KeyboardInterrupt:
        print("HyperCore stopped by keyboard interrupt.", file=sys.stderr)
        return 130
    except Exception as exc:
        if CORE_DEBUG:
            traceback.print_exc()
        else:
            print(f"HyperCore failed to start: {exc}", file=sys.stderr)
        return 2 if args.health else 1


if __name__ == "__main__":
    raise SystemExit(main())
