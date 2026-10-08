from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import ValidationError

from app.schemas import LogEvent
from demo.server_log_demo import DEFAULT_API_URL


MAX_EVENT_BYTES = 262_144


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Follow a JSON-lines server log file and forward new events."
    )
    parser.add_argument(
        "log_file",
        type=Path,
        help="JSON-lines file to follow",
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"log ingestion endpoint (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between file checks (default: 0.5)",
    )
    args = parser.parse_args()
    if args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero")
    if not args.api_url.startswith(("http://", "https://")):
        parser.error("--api-url must start with http:// or https://")
    return args


def validate_event_line(line: bytes, line_number: int) -> dict[str, Any]:
    if len(line) > MAX_EVENT_BYTES:
        raise ValueError(f"line {line_number} exceeds the 256 KB event limit")
    try:
        event = LogEvent.model_validate_json(line)
    except ValidationError as error:
        raise ValueError(f"line {line_number} is not a valid log event") from error
    result: dict[str, Any] = json.loads(line)
    if event.timestamp.tzinfo is None or event.timestamp.utcoffset() is None:
        raise ValueError(f"line {line_number} timestamp must include a timezone")
    return result


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
    log_path = args.log_file.resolve()
    if not log_path.is_file():
        print(f"Log file does not exist: {log_path}", file=sys.stderr)
        return 2

    api_key = os.environ.pop("LOG_MONITORING_API_KEY", "")
    if not api_key:
        api_key = getpass.getpass("Paste the API key for the selected organization: ")
    if not api_key.startswith("lm_") or len(api_key) < 20:
        print("Invalid API key format; expected a key beginning with lm_.", file=sys.stderr)
        return 2

    line_number = 0
    pending = bytearray()
    position = log_path.stat().st_size
    print(f"Following new JSON log lines in {log_path}")
    print("Existing lines are skipped. Press Ctrl+C to stop.")

    try:
        while True:
            file_size = log_path.stat().st_size
            if file_size < position:
                position = 0
                pending.clear()
                print("Log file was truncated; following it from the beginning.")

            with log_path.open("rb") as log_file:
                log_file.seek(position)
                chunk = log_file.read()
            position += len(chunk)
            pending.extend(chunk)

            while b"\n" in pending:
                raw_line, _, remainder = pending.partition(b"\n")
                pending = bytearray(remainder)
                line_number += 1
                if not raw_line.strip():
                    continue

                event = validate_event_line(raw_line, line_number)
                try:
                    send_event(args.api_url, api_key, event)
                except urllib.error.HTTPError as error:
                    print(
                        f"API returned HTTP {error.code} for file line {line_number}; "
                        "stopping.",
                        file=sys.stderr,
                    )
                    return 1
                except urllib.error.URLError as error:
                    print(
                        f"Could not reach the ingestion API for file line {line_number}: "
                        f"{error.reason}",
                        file=sys.stderr,
                    )
                    return 1

                print(
                    f"Forwarded file line {line_number}: "
                    f"{event['severity']} / {event['service']}"
                )

            if len(pending) > MAX_EVENT_BYTES:
                raise ValueError(
                    f"unfinished log line exceeds the 256 KB event limit "
                    f"after line {line_number}"
                )
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except (OSError, ValueError) as error:
        print(f"Log follower stopped: {error}", file=sys.stderr)
        return 1
    finally:
        api_key = ""

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
