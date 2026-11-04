"""``opspilot-mcp serve --profile read|actions [--transport stdio|streamable-http]``."""

from __future__ import annotations

import argparse

from opspilot_shared.config import get_settings
from opspilot_shared.logging import configure_logging


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="opspilot-mcp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--profile", choices=["read", "actions"], required=True)
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default=None)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)  # logs → stderr; stdout carries MCP frames
    from opspilot_mcp.action_server import build_action_server
    from opspilot_mcp.backend import OpsBackend
    from opspilot_mcp.read_server import build_read_server

    backend = OpsBackend.create(settings)
    server = build_read_server(backend) if args.profile == "read" else build_action_server(backend)
    transport = args.transport or settings.mcp_transport
    if transport == "stdio":
        server.run("stdio")
    else:
        port = settings.mcp_http_port + (0 if args.profile == "read" else 1)
        server.run("streamable-http", host=settings.mcp_http_host, port=port)


if __name__ == "__main__":
    main()
