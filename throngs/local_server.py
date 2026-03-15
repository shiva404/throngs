"""
Start the Throngs dashboard server locally.

Usage:
    python local_server.py
    python local_server.py --port 9000
    python local_server.py --host 0.0.0.0 --port 8765 --reload
    python local_server.py --no-verbose   # INFO log level only
"""

import argparse
import logging
import uvicorn

from throngs.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Throngs local dashboard server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes")
    parser.add_argument("--verbose", "-v", action="store_true", default=True, help="Enable debug logging (default: on)")
    parser.add_argument("--no-verbose", action="store_false", dest="verbose", help="Use INFO log level only")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    uv_log_level = "debug" if args.verbose else "info"
    logger.info("Starting dashboard on http://%s:%s (log_level=%s)", args.host, args.port, uv_log_level)

    print(f"\n  Throngs Dashboard")
    print(f"  ─────────────────────────────────────")
    print(f"  Dashboard  →  http://{args.host}:{args.port}/")
    print(f"  Street 3D  →  http://{args.host}:{args.port}/street")
    print(f"  SSE stream →  http://{args.host}:{args.port}/stream")
    print(f"  POST event →  http://{args.host}:{args.port}/event")
    print(f"  ─────────────────────────────────────")
    print(f"  Run agents with:")
    print(f"    throngs --dashboard-url http://{args.host}:{args.port} --url <QB_URL> ...\n")

    uvicorn.run(
        "throngs.dashboard.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=uv_log_level,
    )


if __name__ == "__main__":
    main()
