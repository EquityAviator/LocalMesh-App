"""WP-08 end-to-end smoke test against a REAL uvicorn process.

Validates (§10.5/§10.6, §17.3, §15.4):
  1. `localmesh-agent run` (no dev flag) starts TLS 1.3 public listener + admin listener
  2. TLS 1.3 negotiated; TLS 1.2 refused
  3. GET /mesh/v1/info (unauth) 200 with pairing_open
  4. admin token file created 0600
  5. CLI `pair --no-wait` prints the QR
  6. pair/complete → approve → auth/challenge → auth/token → /models 200
  7. admin /admin/devices lists the device
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path("/home/z/my-project")
AGENT_SRC = REPO / "agent" / "src"
sys.path.insert(0, str(AGENT_SRC))

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from localmesh_agent.security import crypto

PUBLIC_PORT = 18443
ADMIN_PORT = 18444
BASE = f"https://127.0.0.1:{PUBLIC_PORT}"
ADMIN = f"http://127.0.0.1:{ADMIN_PORT}"

PASS = []


def ok(name: str, detail: str = "") -> None:
    PASS.append(name)
    print(f"  PASS {name} {detail}")


def https_request(
    path: str,
    body: dict | None = None,
    token: str | None = None,
    method: str | None = None,
) -> tuple[int, dict, object]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # pin would be verified from the QR in real use
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method or ("POST" if data else "GET")
    )
    if data:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), resp
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), e


def tls_handshake(max_version: ssl.TLSVersion) -> str | None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.maximum_version = max_version
    try:
        with socket.create_connection(("127.0.0.1", PUBLIC_PORT), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname="127.0.0.1") as tls:
                return tls.version()
    except (ssl.SSLError, ConnectionResetError, OSError):
        return None


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wp08-smoke-"))
    config = tmp / "config.toml"
    config.write_text(
        f'[agent]\ndata_dir = "{tmp / "data"}"\n\n'
        f"[listen]\nport = {PUBLIC_PORT}\nadmin_port = {ADMIN_PORT}\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(AGENT_SRC)
    proc = subprocess.Popen(
        [
            str(REPO / "agent" / ".venv" / "bin" / "python"),
            "-m",
            "localmesh_agent",
            "run",
            "--config",
            str(config),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # --- wait for the listener ---
        deadline = time.time() + 15
        info = None
        status = 0
        while time.time() < deadline:
            try:
                status, info, _ = https_request("/mesh/v1/info")
                break
            except Exception:
                time.sleep(0.4)
        assert info is not None, "agent did not come up"
        assert status == 200 and info["agent_id"].startswith("ag_")
        assert info["pairing_open"] is False
        ok("1. public TLS listener up, /info 200 unauth", f"agent_id={info['agent_id'][:14]}...")

        # --- TLS version behaviour (§17.3) ---
        assert tls_handshake(ssl.TLSVersion.MAXIMUM_SUPPORTED) == "TLSv1.3"
        ok("2. TLS 1.3 negotiated", "TLSv1.3")
        assert tls_handshake(ssl.TLSVersion.TLSv1_2) is None, "TLS 1.2 was NOT refused"
        ok("3. TLS 1.2 refused (TLS 1.3 only)")

        # --- admin token file (§17.6) ---
        admin_token_file = tmp / "data" / "admin.token"
        assert admin_token_file.exists()
        mode = stat.S_IMODE(admin_token_file.stat().st_mode)
        assert mode == 0o600, oct(mode)
        admin_token = admin_token_file.read_text().strip()
        ok("4. admin.token created, mode 0600")

        # --- CLI pair --no-wait (prints QR) ---
        cli = subprocess.run(
            [
                str(REPO / "agent" / ".venv" / "bin" / "python"),
                "-m",
                "localmesh_agent",
                "pair",
                "--config",
                str(config),
                "--no-wait",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert cli.returncode == 0, cli.stdout + cli.stderr
        assert "localmesh://pair?v=1&" in cli.stdout
        ok("5. CLI pair --no-wait opened pairing + printed QR")

        # --- complete pairing from the "phone" side (§15.4 steps 5-6) ---
        qr = next(l for l in cli.stdout.splitlines() if l.startswith("localmesh://pair"))
        query = dict(p.split("=", 1) for p in qr.removeprefix("localmesh://pair?").split("&"))
        secret = crypto.b64url_decode(query["sec"])
        key = ec.generate_private_key(ec.SECP256R1())
        spki = key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        nonce = bytes(range(16))
        proof = crypto.pairing_proof(secret, query["aid"], query["pid"], nonce, spki)
        status, body, _ = https_request(
            "/mesh/v1/pair/complete",
            {
                "pair_id": query["pid"],
                "client_nonce": crypto.b64url_encode(nonce),
                "device_name": "SmokePhone",
                "platform": "android",
                "device_public_key_spki": crypto.b64url_encode(spki),
                "proof": crypto.b64url_encode(proof),
            },
        )
        assert status == 202, (status, body)
        status, info2, _ = https_request("/mesh/v1/info")
        # pairing_open = "accepts NEW pair/complete claims" — the claimed
        # session's secret is single-use (§15.2), so it is no longer open.
        assert info2["pairing_open"] is False
        ok("6. pair/complete 202 (claimed, awaiting confirmation)")

        # --- admin: pending shows SAS; approve ---
        req = urllib.request.Request(ADMIN + "/admin/pair/pending")
        req.add_header("X-Admin-Token", admin_token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            pending = json.loads(resp.read())
        assert pending["state"] == "claimed" and len(pending["sas"]) == 6
        req = urllib.request.Request(ADMIN + "/admin/pair/approve", method="POST")
        req.add_header("X-Admin-Token", admin_token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            approved = json.loads(resp.read())
        device_id = approved["device_id"]
        assert device_id.startswith("dv_")
        ok("7. admin pending SAS + approve", f"device={device_id[:11]}...")

        # --- status poll → approved (§15.4 step 11) ---
        status_proof = crypto.status_proof(secret, query["pid"], nonce)
        status, body, _ = https_request(
            "/mesh/v1/pair/status",
            {
                "pair_id": query["pid"],
                "client_nonce": crypto.b64url_encode(nonce),
                "status_proof": crypto.b64url_encode(status_proof),
            },
        )
        assert status == 200 and body["status"] == "approved" and body["device_id"] == device_id
        ok("8. pair/status → approved with device_id + scopes")

        # --- auth challenge/token (ADR-008) ---
        status, challenge, _ = https_request("/mesh/v1/auth/challenge", {"device_id": device_id})
        assert status == 200
        message = crypto.auth_message(
            query["aid"], device_id, challenge["challenge_id"], challenge["nonce"]
        )
        signature = crypto.b64url_encode(key.sign(message, ec.ECDSA(hashes.SHA256())))
        status, tok, _ = https_request(
            "/mesh/v1/auth/token",
            {
                "device_id": device_id,
                "challenge_id": challenge["challenge_id"],
                "signature": signature,
            },
        )
        assert status == 200, (status, tok)
        assert tok["token_type"] == "Bearer" and tok["expires_in"] == 900
        assert tok["scopes"] == ["models:read", "chat"]
        ok("9. auth/challenge + auth/token -> Bearer token (900s)")

        # --- authenticated /models + /health ---
        status, models, _ = https_request("/mesh/v1/models", token=tok["access_token"])
        assert status == 200, (status, models)
        status, health, _ = https_request("/mesh/v1/health", token=tok["access_token"])
        assert status == 200
        ok("10. Bearer works on /models + /health (token mode, no dev flag)")

        # --- admin devices listing (§15.6 surface) ---
        req = urllib.request.Request(ADMIN + "/admin/devices")
        req.add_header("X-Admin-Token", admin_token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            devices = json.loads(resp.read())["devices"]
        assert len(devices) == 1 and devices[0]["device_id"] == device_id
        assert "public_key_spki" not in devices[0]
        ok("11. admin /admin/devices lists the paired device")

        # --- unauthorized /models still fails closed (SEC-N4) ---
        status, body, _ = https_request("/mesh/v1/models")
        assert status == 401 and body["error"]["code"] == "AUTH_REQUIRED"
        ok("12. no-token /models -> 401 AUTH_REQUIRED (fail-closed)")
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            proc.kill()
            out = proc.communicate()[0]
        # §17.6/§17.10: the pairing secret must never be logged by the agent
        if "sec=" in out:
            print("FAIL: pairing secret leaked into agent logs")
            print(out[-2000:])
            return 1
    print(f"\nSMOKE OK - {len(PASS)}/12 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
