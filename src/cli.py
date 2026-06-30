"""
AgentBridge CLI — `python -m src.cli <command>` (or `agentbridge <command>` once installed).

Commands:
  serve       Start the control-plane HTTP API (uvicorn)
  mcp         Start the drop-in MCP server (stdio)
  translate   Show a one-off any-to-any protocol translation
  demo        Run the 60-second demo story
  quickstart  Run the zero-governance quickstart
  version     Print the version
"""

import argparse
import json
import os
import runpy
import sys

from . import __version__


def _serve(args):
    import uvicorn
    # Production-grade defaults: no reload, explicit host/port, graceful drain via
    # AGENTBRIDGE_SHUTDOWN_GRACE. Reload is opt-in (--reload) for development only.
    uvicorn.run(
        "src.api.control_plane:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,  # reload + workers is incompatible
        log_level=args.log_level,
        access_log=False,  # we have our own structured middleware; uvicorn access logs are noisy
        timeout_graceful_shutdown=int(float(os.getenv("AGENTBRIDGE_SHUTDOWN_GRACE", "10")) * 1000),
    )


def _mcp(args):
    # Mirrors `python -m src.serve.mcp_gateway` so we don't assume a specific entrypoint name.
    runpy.run_module("src.serve.mcp_gateway", run_name="__main__")


def _translate(args):
    from .protocols import default_registry as reg
    from .protocols.canonical import CanonicalCall

    src_wire = reg.get(args.from_).from_canonical_call(CanonicalCall(args.tool, args.args))
    dst_wire = reg.translate_call(src_wire, args.from_, args.to)
    print(f"\n{args.from_} -> {args.to}  (tool: {args.tool}, args: {args.args})")
    print(f"  source wire: {src_wire}")
    print(f"  target wire: {dst_wire}\n")


def _demo(args):
    runpy.run_module("examples.demo_story", run_name="__main__")


def _quickstart(args):
    runpy.run_module("examples.quickstart", run_name="__main__")


def main():
    p = argparse.ArgumentParser(
        prog="agentbridge",
        description="AgentBridge — the Meta-Bridge: translate, route, verify, govern AI-agent calls.",
    )
    p.add_argument("--version", action="store_true", help="show version and exit")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("serve", help="Start the control-plane HTTP API")
    sp.add_argument("--host", default="0.0.0.0")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--reload", action="store_true",
                    help="dev mode: auto-reload on file changes (disables --workers)")
    sp.add_argument("--workers", type=int, default=1,
                    help="uvicorn worker processes (requires a durable AGENTBRIDGE_DB)")
    sp.add_argument("--log-level", default=os.getenv("AGENTBRIDGE_LOG_LEVEL", "info").lower(),
                    choices=["critical", "error", "warning", "info", "debug", "trace"])

    sub.add_parser("mcp", help="Start the drop-in MCP server (stdio)")
    sub.add_parser("demo", help="Run the 60-second demo story")
    sub.add_parser("quickstart", help="Run the zero-governance quickstart")

    tp = sub.add_parser("translate", help="Show a one-off protocol translation")
    tp.add_argument("--from", dest="from_", required=True, help="source protocol (e.g. openai)")
    tp.add_argument("--to", required=True, help="target protocol (e.g. mcp)")
    tp.add_argument("--tool", default="add", help="capability/tool name")
    tp.add_argument("--args", type=json.loads, default={"a": 2, "b": 3},
                    help='arguments as JSON, e.g. \'{"a":2,"b":3}\'')

    args = p.parse_args()
    if args.version:
        print(f"AgentBridge {__version__}")
        return
    if not args.command:
        p.print_help()
        return

    {"serve": _serve, "mcp": _mcp, "translate": _translate,
     "demo": _demo, "quickstart": _quickstart}[args.command](args)


if __name__ == "__main__":
    main()
