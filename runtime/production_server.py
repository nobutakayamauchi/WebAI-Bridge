from __future__ import annotations

import argparse

import uvicorn

EXPECTED_APP = "commercial_handoff:app"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WebAI Bridge pinned production server")
    parser.add_argument("app")
    parser.add_argument("--no-access-log", action="store_true")
    args = parser.parse_args(argv)
    if args.app != EXPECTED_APP:
        parser.error(f"production app must be exactly {EXPECTED_APP}")
    if not args.no_access_log:
        parser.error("production access logging must remain disabled")

    uvicorn.run(
        EXPECTED_APP,
        host="127.0.0.1",
        port=8080,
        workers=1,
        reload=False,
        factory=False,
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
