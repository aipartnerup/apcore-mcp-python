"""CLI entry point: python -m apcore_mcp."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from apcore.registry import Registry

from apcore_mcp import serve

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for apcore-mcp CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m apcore_mcp",
        description="Launch an MCP server that exposes apcore modules as tools.",
    )

    # Required
    parser.add_argument(
        "--extensions-dir",
        required=True,
        type=Path,
        help="Path to apcore extensions directory.",
    )

    # Transport options
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="stdio",
        help="Transport type (default: stdio).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address for HTTP-based transports (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP-based transports (default: 8000, range: 1-65535).",
    )

    # Server options
    parser.add_argument(
        "--name",
        default="apcore-mcp",
        help='MCP server name (default: "apcore-mcp", max 255 chars).',
    )
    parser.add_argument(
        "--version",
        default=None,
        help="MCP server version (default: package version).",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Logging level (default: INFO).",
    )

    return parser


def _validate_port(port: int, parser: argparse.ArgumentParser) -> None:
    """Validate port is in range 1-65535."""
    if port < 1 or port > 65535:
        parser.error(f"--port must be in range 1-65535, got {port}")


def main() -> None:
    """CLI entry point for launching apcore-mcp server.

    Exit codes:
        0 - Normal shutdown
        1 - Invalid arguments (non-existent directory, invalid port, name too long)
        2 - Startup failure (argparse error, serve() exception)
    """
    parser = _build_parser()
    args = parser.parse_args()

    # Validate port range (argparse only validates type, not range)
    _validate_port(args.port, parser)

    # Validate --extensions-dir exists and is a directory
    extensions_dir: Path = args.extensions_dir
    if not extensions_dir.exists():
        print(
            f"Error: --extensions-dir '{extensions_dir}' does not exist.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not extensions_dir.is_dir():
        print(
            f"Error: --extensions-dir '{extensions_dir}' is not a directory.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate name length
    if len(args.name) > 255:
        print(
            f"Error: --name must be at most 255 characters, got {len(args.name)}.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Create Registry and discover modules
    registry = Registry(extensions_dir=str(extensions_dir))
    num_modules = registry.discover()

    if num_modules == 0:
        logger.warning("No modules discovered in '%s'.", extensions_dir)
    else:
        logger.info("Discovered %d module(s) in '%s'.", num_modules, extensions_dir)

    # Launch the MCP server
    try:
        serve(
            registry,
            transport=args.transport,
            host=args.host,
            port=args.port,
            name=args.name,
            version=args.version,
        )
    except Exception:
        logger.exception("Server startup failed.")
        sys.exit(2)


if __name__ == "__main__":
    main()
