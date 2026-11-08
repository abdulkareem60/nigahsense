"""Send the contract example event to a running API, as the vision worker would.

Usage:  python scripts/send_sample_event.py --key <worker key> [--api http://127.0.0.1:8000] [--repeat 2]
A fresh event_id is used each run; --repeat re-sends the same event to show duplicate handling.
"""

import argparse
import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "vision-event.v1.restricted-zone-entry.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8000")
    p.add_argument("--key", default=os.environ.get("NIGAHSENSE_WORKER_KEY", ""))
    p.add_argument("--repeat", type=int, default=1)
    a = p.parse_args()

    event = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    event["event_id"] = str(uuid.uuid4())
    for _ in range(max(1, a.repeat)):
        req = urllib.request.Request(f"{a.api}/v1/events", data=json.dumps(event).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Worker-Key": a.key})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                print(r.status, r.read().decode())
        except urllib.error.HTTPError as e:
            print(e.code, e.read().decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
