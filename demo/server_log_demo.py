from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "demo" / "server.log"
DEFAULT_API_URL = "http://127.0.0.1:8000/v1/logs"
SEVERITIES = ("info", "warning", "error")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate JSON server logs and send them to the local log API."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="number of log events to generate (default: 5)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="seconds between events (default: 3)",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"log ingestion endpoint (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--file-only",
        action="store_true",
        help="write log events to the file without sending them to the API",
    )
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be at least 1")
    if args.interval < 0:
        parser.error("--interval cannot be negative")
    if not args.api_url.startswith(("http://", "https://")):
        parser.error("--api-url must start with http:// or https://")
    return args


def make_event(sequence: int, run_id: str) -> dict[str, Any]:
    severity = SEVERITIES[(sequence - 1) % len(SEVERITIES)]
    messages = {
        "info": "Request completed successfully",
        "warning": "Request latency exceeded the normal threshold",
        "error": "Simulated payment provider timeout",
    }
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": severity,
        "service": "demo-api",
        "message": messages[severity],
        "environment": "development",
        "attributes": {
            "source": "server-log-file-demo",
            "run_id": run_id,
            "sequence": sequence,
            "http_status": {"info": 200, "warning": 200, "error": 504}[severity],
        },
    }


def send_event(api_url: str, api_key: str, event: dict[str, Any]) -> None:
    request = urllib.request.Request(
        api_url,
        data=json.dumps(event).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 202:
            raise RuntimeError(f"ingestion API returned HTTP {response.status}")


def main() -> int:
    args = parse_args()
    api_key = ""
    if not args.file_only:
        api_key = os.environ.pop("LOG_MONITORING_API_KEY", "")
    if not args.file_only and not api_key:
        api_key = getpass.getpass("Paste the API key for the selected organization: ")
    if not args.file_only and (not api_key.startswith("lm_") or len(api_key) < 20):
        print("Invalid API key format; expected a key beginning with lm_.", file=sys.stderr)
        return 2

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    print(f"Appending generated events to {LOG_PATH}")
    print("Writing file-only events." if args.file_only else "Press Ctrl+C to stop early.")

    try:
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            for sequence in range(1, args.count + 1):
                event = make_event(sequence, run_id)
                line = json.dumps(event, separators=(",", ":"))
                log_file.write(line + "\n")
                log_file.flush()

                if not args.file_only:
                    try:
                        send_event(args.api_url, api_key, event)
                    except urllib.error.HTTPError as error:
                        print(
                            f"Event {sequence} was written to the file but API returned "
                            f"HTTP {error.code}; stopping.",
                            file=sys.stderr,
                        )
                        return 1
                    except urllib.error.URLError as error:
                        print(
                            f"Event {sequence} was written to the file but API could not "
                            f"be reached: {error.reason}; stopping.",
                            file=sys.stderr,
                        )
                        return 1

                action = "wrote" if args.file_only else "generated and sent"
                print(f"{action.capitalize()} event {sequence}/{args.count} ({event['severity']})")
                if sequence < args.count:
                    time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        api_key = ""

    api_key = ""
    print(f"Log file: {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
