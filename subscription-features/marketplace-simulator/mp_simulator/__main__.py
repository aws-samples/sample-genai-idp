"""CLI entrypoint: ``python -m mp_simulator serve --port 9999 --db mp.sqlite``."""

from __future__ import annotations

import argparse
import logging
import sys

from . import server


def main() -> int:
    ap = argparse.ArgumentParser(prog="mp-simulator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run the simulator HTTP server")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=9999)
    p_serve.add_argument("--db", default="mp-sim.sqlite", help="SQLite database path")
    p_serve.add_argument("-v", "--verbose", action="store_true")

    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.cmd == "serve":
        srv = server.serve(host=args.host, port=args.port, db_path=args.db)
        print(
            f"mp-simulator listening on http://{args.host}:{srv.server_address[1]}  (db={args.db})",
            flush=True,
        )
        print(
            "Point boto3 clients at this URL via:\n"
            f"  export AWS_ENDPOINT_URL_METERINGMARKETPLACE=http://{args.host}:{srv.server_address[1]}\n"
            f"  export AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT=http://{args.host}:{srv.server_address[1]}",
            flush=True,
        )
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            srv.shutdown()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
