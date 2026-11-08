"""Print a Firebase ID token for a local operator account (Auth EMULATOR only).

Creates the user if needed, sets the custom claim {"role": <role>}, signs in and prints the token.
Usage (emulator running):  python scripts/dev_operator_token.py [--email op@nigahsense.test] [--role operator]
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

PASSWORD = "local-dev-only-password"


def call(url: str, body: dict, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"error": json.loads(e.read() or b"{}").get("error", {"message": str(e)})}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--email", default="operator@nigahsense.test")
    p.add_argument("--role", default="operator")
    p.add_argument("--project", default=os.environ.get("FIREBASE_PROJECT_ID", "demo-nigahsense"))
    p.add_argument("--host", default=os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099"))
    a = p.parse_args()

    base = f"http://{a.host}/identitytoolkit.googleapis.com/v1"
    creds = {"email": a.email, "password": PASSWORD, "returnSecureToken": True}
    user = call(f"{base}/accounts:signUp?key=emulator", creds)
    if "error" in user:
        user = call(f"{base}/accounts:signInWithPassword?key=emulator", creds)
    if "error" in user:
        print(f"Auth emulator error: {user['error']}. Is it running on {a.host}?", file=sys.stderr)
        return 1

    # "Bearer owner" is the Auth emulator's admin credential; it does not work against real Firebase.
    upd = call(f"{base}/projects/{a.project}/accounts:update", {"localId": user["localId"], "customAttributes": json.dumps({"role": a.role})}, {"Authorization": "Bearer owner"})
    if "error" in upd:
        print(f"Could not set role: {upd['error']}", file=sys.stderr)
        return 1

    token = call(f"{base}/accounts:signInWithPassword?key=emulator", creds)["idToken"]
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
