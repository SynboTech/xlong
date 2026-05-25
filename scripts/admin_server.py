#!/usr/bin/env python3
from __future__ import annotations

import json
import hashlib
import hmac
import os
import secrets
import sys
import tempfile
import time
import asyncio
from decimal import Decimal, InvalidOperation
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.common.types import to_jsonable
from mm.config.audit import build_config_audit
from mm.config.settings import AppSettings
from mm.exchange.bitmart.rest import BitMartRestGateway
from mm.persistence.order_store import build_order_store
from mm.persistence.replay import EventLogReplay


CONFIG_PATH = os.path.join(ROOT, "config/paper.json")
ORDERS_PATH = os.path.join(ROOT, "runtime/orders.json")
EVENTS_PATH = os.path.join(ROOT, "runtime/events.jsonl")
EXCHANGES_PATH = os.path.join(ROOT, "runtime/exchanges.json")
STRATEGY_STATE_PATH = os.path.join(ROOT, "runtime/strategy_state.json")
RISK_STATE_PATH = os.path.join(ROOT, "runtime/risk_state.json")
RUNTIME_COMMANDS_PATH = os.path.join(ROOT, "runtime/commands.json")
ADMIN_AUDIT_PATH = os.path.join(ROOT, "runtime/admin_audit.jsonl")
ADMIN_TOKEN_PATH = os.path.join(ROOT, "runtime/admin_token.json")
ADMIN_USERS_PATH = os.path.join(ROOT, "runtime/admin_users.json")


ROLE_PERMISSIONS = {
    "viewer": {"read"},
    "operator": {"read", "operate"},
    "admin": {"read", "operate", "configure", "trade", "admin"},
}

POST_PERMISSIONS = {
    "/api/exchanges": "configure",
    "/api/exchanges/test": "read",
    "/api/symbols": "configure",
    "/api/symbols/delete": "admin",
    "/api/strategies": "configure",
    "/api/strategies/delete": "admin",
    "/api/strategies/state": "operate",
    "/api/strategies/stop-cancel": "operate",
    "/api/orders/cancel-plan": "operate",
    "/api/risk/kill-switch": "operate",
    "/api/auth/logout": "read",
}


SECURITY = None


class AdminHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/api/auth/me":
            principal = self._authorize("GET", path, None)
            if principal is None:
                return
            return self._json({"ok": True, "user": principal})
        if path == "/api/security/audit":
            principal = self._authorize("GET", path, None)
            if principal is None:
                return
            return self._json(admin_security().audit_payload())
        if path not in {"/", "/index.html"} and not path.startswith("/docs/"):
            principal = self._authorize("GET", path, None)
            if principal is None:
                return
        if path == "/api/config":
            return self._json({"config": read_config(), "audit": audit_dict()})
        if path == "/api/exchanges":
            return self._json(exchange_payload())
        if path == "/api/symbols":
            return self._json(symbol_payload())
        if path == "/api/strategies":
            return self._json(strategy_payload())
        if path == "/api/strategies/detail":
            key = first_query_value(query, "key", "")
            return self._json(strategy_detail_payload(key))
        if path == "/api/orders":
            source = first_query_value(query, "source", "local")
            if source == "remote":
                return self._json(remote_order_payload())
            return self._json(order_payload())
        if path == "/api/orders/remote":
            return self._json(remote_order_payload())
        if path == "/api/orders/reconcile":
            return self._json(reconcile_payload())
        if path == "/api/fills":
            return self._json(fill_payload())
        if path == "/api/inventory":
            return self._json(inventory_payload())
        if path == "/api/market/history":
            symbol = first_query_value(query, "symbol", None)
            limit = int(first_query_value(query, "limit", "160"))
            return self._json(market_history_payload(symbol=symbol, limit=limit))
        if path == "/api/risk":
            return self._json(risk_payload())
        if path == "/api/events/summary":
            return self._json(event_summary())
        if path == "/api/health":
            return self._json({"ok": True, "mode": "local_admin"})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json(default={})
        if path == "/api/auth/login":
            payload = admin_security().login(body)
            return self._json(payload, status=200 if payload.get("ok") else 401)

        principal = self._authorize("POST", path, body)
        if principal is None:
            return
        permission_error = execution_permission_error_for(principal, path, body)
        if permission_error:
            payload = {"ok": False, "error": permission_error, "required_permission": "trade"}
            admin_security().append_audit(principal, path, body, payload, 403)
            return self._json(payload, status=403)
        confirmation_error = confirmation_error_for(path, body)
        if confirmation_error:
            payload = {"ok": False, "error": confirmation_error}
            admin_security().append_audit(principal, path, body, payload, 409)
            return self._json(payload, status=409)

        if path == "/api/exchanges":
            return self._json_audited(principal, path, body, save_exchange_account(body))

        if path == "/api/auth/logout":
            return self._json_audited(principal, path, body, admin_security().logout(self.headers))

        if path == "/api/exchanges/test":
            return self._json_audited(principal, path, body, test_exchange_account(body))

        if path == "/api/symbols":
            return self._json_audited(principal, path, body, save_symbol(body))

        if path == "/api/symbols/delete":
            return self._json_audited(principal, path, body, delete_symbol(body))

        if path == "/api/strategies":
            config = read_config()
            strategies = config.setdefault("strategies", [])
            name = str(body["name"])
            symbol = str(body["symbol"]).upper()
            instance_id = str(body.get("id") or body.get("key") or body.get("instance_id") or "").strip()
            if instance_id:
                instance_id = slug(instance_id)
            item = {
                "name": name,
                "symbol": symbol,
                "enabled": bool(body.get("enabled", True)),
                "params": body.get("params", {}),
            }
            if instance_id:
                item["id"] = instance_id
            replaced = False
            for idx, existing in enumerate(strategies):
                if strategy_key(existing) == strategy_key(item):
                    strategies[idx] = item
                    replaced = True
                    break
                if not instance_id and not existing.get("id") and existing.get("name") == name and existing.get("symbol") == symbol:
                    strategies[idx] = item
                    replaced = True
                    break
            if not replaced:
                strategies.append(item)
            write_config(config)
            return self._json_audited(principal, path, body, {"ok": True, "config": config, "audit": audit_dict()})

        if path == "/api/strategies/delete":
            result = delete_strategy(body)
            return self._json_audited(principal, path, body, result, status=200 if result.get("ok") else 409)

        if path == "/api/strategies/state":
            return self._json_audited(principal, path, body, update_strategy_state(body))

        if path == "/api/strategies/stop-cancel":
            result = stop_cancel_strategy(body)
            return self._json_audited(principal, path, body, result, status=200 if result.get("ok") else 409)

        if path == "/api/orders/cancel-plan":
            return self._json_audited(principal, path, body, cancel_plan(body.get("symbol"), body.get("strategy")))

        if path == "/api/risk/kill-switch":
            return self._json_audited(principal, path, body, update_kill_switch(body))

        payload = {"ok": False, "error": "unknown endpoint"}
        admin_security().append_audit(principal, path, body, payload, 404)
        return self._json(payload, status=404)

    def _read_json(self, default=None):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return default if default is not None else {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json_audited(self, principal, path, body, payload, status=200):
        admin_security().append_audit(principal, path, body, payload, status)
        return self._json(payload, status=status)

    def _authorize(self, method, path, body):
        principal = admin_security().authenticate(self.headers)
        if principal is None:
            payload = {"ok": False, "error": "admin authentication required"}
            admin_security().append_audit(admin_security().anonymous(), path, body or {}, payload, 401)
            self._json(payload, status=401)
            return None
        permission = permission_for(method, path)
        if permission and not admin_security().allowed(principal, permission):
            payload = {"ok": False, "error": "permission denied", "required_permission": permission}
            admin_security().append_audit(principal, path, body or {}, payload, 403)
            self._json(payload, status=403)
            return None
        return principal


class AdminSecurity:
    def __init__(
        self,
        tokens=None,
        users=None,
        audit_path=None,
        token_path=None,
        users_path=None,
        audit_secret=None,
        session_ttl_sec=None,
    ):
        self.audit_path = audit_path or ADMIN_AUDIT_PATH
        self.token_path = token_path or ADMIN_TOKEN_PATH
        self.users_path = users_path or ADMIN_USERS_PATH
        self.tokens = tokens if tokens is not None else self._load_tokens()
        self.users = users if users is not None else self._load_users()
        self.sessions = {}
        self.session_ttl_ms = int(session_ttl_sec or os.environ.get("ADMIN_SESSION_TTL_SEC", "28800")) * 1000
        self.audit_secret = audit_secret or os.environ.get("ADMIN_AUDIT_SECRET") or self._first_token()

    def _load_tokens(self):
        tokens = {}
        self._add_env_token(tokens, "ADMIN_TOKEN", "admin", "admin")
        self._add_env_token(tokens, "ADMIN_OPERATOR_TOKEN", "operator", "operator")
        self._add_env_token(tokens, "ADMIN_VIEWER_TOKEN", "viewer", "viewer")
        if tokens:
            return tokens
        token = self._load_or_create_local_token()
        return {token: {"user": "local-admin", "role": "admin"}}

    @staticmethod
    def _add_env_token(tokens, env_name, user, role):
        token = os.environ.get(env_name, "")
        if token:
            tokens[token] = {"user": user, "role": role}

    def _load_or_create_local_token(self):
        data = read_json_file(self.token_path, {})
        token = data.get("token")
        if token:
            return str(token)
        token = secrets.token_urlsafe(32)
        write_json_file(
            self.token_path,
            {
                "token": token,
                "role": "admin",
                "created_at_ms": now_ms(),
                "message": "Local development admin token. Set ADMIN_TOKEN in production.",
            },
        )
        return token

    def _load_users(self):
        users = {}
        self._add_env_user(users, "ADMIN", "admin")
        self._add_env_user(users, "ADMIN_OPERATOR", "operator")
        self._add_env_user(users, "ADMIN_VIEWER", "viewer")
        users_json = os.environ.get("ADMIN_USERS_JSON", "")
        if users_json:
            for item in self._parse_users_json(users_json):
                users[str(item["username"])] = item
        if users:
            return users
        data = read_json_file(self.users_path, {})
        rows = data.get("users", []) if isinstance(data, dict) else []
        for item in rows:
            if isinstance(item, dict) and item.get("username") and item.get("password_hash"):
                users[str(item["username"])] = {
                    "username": str(item["username"]),
                    "password_hash": str(item["password_hash"]),
                    "role": str(item.get("role", "viewer")),
                    "active": bool(item.get("active", True)),
                }
        if users:
            return users
        return self._create_local_admin_user()

    def _add_env_user(self, users, prefix, default_role):
        username = os.environ.get("{0}_USERNAME".format(prefix), "")
        password = os.environ.get("{0}_PASSWORD".format(prefix), "")
        role = os.environ.get("{0}_ROLE".format(prefix), default_role)
        if username and password:
            users[username] = {
                "username": username,
                "password_hash": hash_password(password),
                "role": role,
                "active": True,
            }

    def _parse_users_json(self, users_json):
        parsed = json.loads(users_json)
        rows = []
        if isinstance(parsed, dict):
            for username, item in parsed.items():
                if isinstance(item, dict):
                    row = dict(item)
                    row.setdefault("username", username)
                    rows.append(row)
        else:
            rows = parsed
        result = []
        for item in rows:
            if not isinstance(item, dict) or not item.get("username"):
                continue
            password_hash = item.get("password_hash")
            password = item.get("password")
            if not password_hash and password:
                password_hash = hash_password(str(password))
            if not password_hash:
                continue
            result.append(
                {
                    "username": str(item["username"]),
                    "password_hash": str(password_hash),
                    "role": str(item.get("role", "viewer")),
                    "active": bool(item.get("active", True)),
                }
            )
        return result

    def _create_local_admin_user(self):
        password = secrets.token_urlsafe(18)
        user = {
            "username": "local-admin",
            "password_hash": hash_password(password),
            "role": "admin",
            "active": True,
        }
        write_json_file(
            self.users_path,
            {
                "users": [user],
                "created_at_ms": now_ms(),
                "initial_password": password,
                "message": "Local development admin user. Set ADMIN_USERNAME/ADMIN_PASSWORD in production.",
            },
        )
        return {user["username"]: user}

    def _first_token(self):
        return next(iter(self.tokens.keys()), "admin-audit-dev-secret")

    def anonymous(self):
        return {"user": "anonymous", "role": "anonymous", "permissions": []}

    def authenticate(self, headers):
        token = self._token_from_headers(headers)
        principal = self._session_principal(token)
        auth_type = "session"
        if principal is None:
            principal = self.tokens.get(token)
            auth_type = "token"
        if principal is None:
            return None
        role = principal.get("role", "viewer")
        permissions = sorted(ROLE_PERMISSIONS.get(role, {"read"}))
        return {
            "user": principal.get("user") or principal.get("username") or role,
            "role": role,
            "permissions": permissions,
            "auth_type": auth_type,
        }

    def login(self, body):
        username = str(body.get("username") or "").strip()
        password = str(body.get("password") or "")
        if username or password:
            return self._login_password(username, password)
        token = str(body.get("token") or "")
        principal = self.tokens.get(token)
        if principal is None:
            payload = {"ok": False, "error": "invalid admin token"}
            self.append_audit(self.anonymous(), "/api/auth/login", {}, payload, 401)
            return payload
        role = principal.get("role", "viewer")
        user = {
            "user": principal.get("user", role),
            "role": role,
            "permissions": sorted(ROLE_PERMISSIONS.get(role, {"read"})),
            "auth_type": "token",
        }
        payload = {"ok": True, "user": user, "token": token}
        self.append_audit(user, "/api/auth/login", {}, payload, 200)
        return payload

    def _login_password(self, username, password):
        principal = self.users.get(username)
        request_payload = {"username": username, "password": password}
        if principal is None or not principal.get("active", True) or not verify_password(password, principal.get("password_hash", "")):
            payload = {"ok": False, "error": "invalid username or password"}
            self.append_audit(self.anonymous(), "/api/auth/login", request_payload, payload, 401)
            return payload
        token = "sess_{0}".format(secrets.token_urlsafe(32))
        expires_at_ms = now_ms() + self.session_ttl_ms
        session = {
            "user": principal.get("username", username),
            "role": principal.get("role", "viewer"),
            "expires_at_ms": expires_at_ms,
            "login_at_ms": now_ms(),
        }
        self.sessions[token] = session
        user = {
            "user": session["user"],
            "role": session["role"],
            "permissions": sorted(ROLE_PERMISSIONS.get(session["role"], {"read"})),
            "auth_type": "session",
            "expires_at_ms": expires_at_ms,
        }
        payload = {"ok": True, "user": user, "token": token}
        self.append_audit(user, "/api/auth/login", request_payload, payload, 200)
        return payload

    def logout(self, headers):
        token = self._token_from_headers(headers)
        removed = token in self.sessions
        self.sessions.pop(token, None)
        return {"ok": True, "logged_out": removed}

    def allowed(self, principal, permission):
        return permission in set(principal.get("permissions", []))

    def _session_principal(self, token):
        if not token:
            return None
        session = self.sessions.get(token)
        if session is None:
            return None
        if int(session.get("expires_at_ms", 0)) < now_ms():
            self.sessions.pop(token, None)
            return None
        return session

    @staticmethod
    def _token_from_headers(headers):
        auth = str(headers.get("Authorization") or "")
        if auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return str(headers.get("X-Admin-Token") or "").strip()

    def append_audit(self, principal, path, request_payload, response_payload, status):
        success = 200 <= int(status) < 300 and bool(response_payload.get("ok", True))
        previous = self._last_signature()
        row = {
            "ts": now_ms(),
            "user": principal.get("user", "unknown"),
            "role": principal.get("role", "unknown"),
            "auth_type": principal.get("auth_type", "unknown"),
            "path": path,
            "status": int(status),
            "success": bool(success),
            "request": redact_payload(request_payload or {}),
            "response": redact_payload(response_payload or {}),
            "previous_signature": previous,
        }
        row["signature"] = self._sign(row)
        parent = os.path.dirname(self.audit_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.audit_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return row

    def audit_payload(self, limit=120):
        rows = []
        if os.path.exists(self.audit_path):
            with open(self.audit_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        selected = rows[-limit:]
        return {
            "ok": True,
            "path": self.audit_path,
            "total": len(rows),
            "valid_chain": self.verify_chain(rows),
            "events": selected,
        }

    def verify_chain(self, rows):
        previous = ""
        for row in rows:
            signature = row.get("signature", "")
            if row.get("previous_signature", "") != previous:
                return False
            unsigned = dict(row)
            unsigned.pop("signature", None)
            if not hmac.compare_digest(signature, self._sign(unsigned)):
                return False
            previous = signature
        return True

    def _last_signature(self):
        if not os.path.exists(self.audit_path):
            return ""
        last = ""
        with open(self.audit_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = line
        if not last:
            return ""
        try:
            return str(json.loads(last).get("signature", ""))
        except json.JSONDecodeError:
            return ""

    def _sign(self, payload):
        unsigned = dict(payload)
        unsigned.pop("signature", None)
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hmac.new(self.audit_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def admin_security():
    global SECURITY
    if SECURITY is None:
        SECURITY = AdminSecurity()
    return SECURITY


def permission_for(method, path):
    if path == "/api/security/audit":
        return "admin"
    if method == "GET":
        return "read"
    if method == "POST":
        return POST_PERMISSIONS.get(path, "admin")
    return "admin"


def hash_password(password, iterations=200000):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, int(iterations))
    return "pbkdf2_sha256${0}${1}${2}".format(iterations, salt.hex(), digest.hex())


def verify_password(password, password_hash):
    try:
        scheme, iterations, salt_hex, digest_hex = str(password_hash).split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def redact_payload(value):
    sensitive = {
        "api_key",
        "api_secret",
        "memo",
        "token",
        "authorization",
        "x-admin-token",
        "password",
        "password_hash",
        "initial_password",
        "session",
    }
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in sensitive:
                result[key] = "***"
            else:
                result[key] = redact_payload(item)
        return result
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    return value


def confirmation_error_for(path, body):
    expected = expected_confirmation(path, body)
    if not expected:
        return ""
    actual = str(body.get("confirmation") or "").strip()
    if actual != expected:
        return "confirmation required: {0}".format(expected)
    return ""


def expected_confirmation(path, body):
    if path == "/api/symbols/delete":
        symbol = str(body.get("symbol") or "").upper()
        return "DELETE SYMBOL {0}".format(symbol) if symbol else "DELETE SYMBOL"
    if path == "/api/strategies/delete":
        key = str(body.get("key") or body.get("id") or "").strip()
        if not key and body.get("name") and body.get("symbol"):
            key = "{0}:{1}".format(body.get("name"), str(body.get("symbol")).upper())
        return "DELETE STRATEGY {0}".format(key) if key else "DELETE STRATEGY"
    if path == "/api/strategies/stop-cancel":
        key = str(body.get("key") or body.get("id") or "").strip()
        if not key and body.get("name") and body.get("symbol"):
            key = "{0}:{1}".format(body.get("name"), str(body.get("symbol")).upper())
        if bool(body.get("execute", False)):
            return "EXECUTE LIVE CANCEL {0}".format(key) if key else "EXECUTE LIVE CANCEL"
        return "STOP CANCEL {0}".format(key) if key else "STOP CANCEL"
    if path == "/api/strategies/state":
        action = str(body.get("action") or "").lower()
        if action in {"start", "running"}:
            key = str(body.get("key") or body.get("id") or "").strip()
            if not key and body.get("name") and body.get("symbol"):
                key = "{0}:{1}".format(body.get("name"), str(body.get("symbol")).upper())
            return "START STRATEGY {0}".format(key) if key else "START STRATEGY"
    if path == "/api/risk/kill-switch":
        return "PAUSE NEW ORDERS" if bool(body.get("enabled", True)) else "RESUME NEW ORDERS"
    return ""


def execution_permission_error_for(principal, path, body):
    if path == "/api/strategies/stop-cancel" and bool(body.get("execute", False)):
        if not admin_security().allowed(principal, "trade"):
            return "permission denied: trade permission required for live execution"
    return ""


def read_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_config(config):
    write_json_file(CONFIG_PATH, config)


def read_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json_file(path, payload):
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".{0}-".format(os.path.basename(path)), suffix=".tmp", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def first_query_value(query, key, default):
    values = query.get(key)
    if not values:
        return default
    return values[0]


def now_ms():
    return int(time.time() * 1000)


def slug(value):
    text = str(value or "").lower()
    chars = []
    previous_dash = False
    for char in text:
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    return "".join(chars).strip("-") or "item"


def strategy_key(item):
    return str(item.get("id") or "{0}:{1}".format(item.get("name", ""), item.get("symbol", "")))


def strategy_order_keys(item):
    keys = {strategy_key(item)}
    if not item.get("id"):
        keys.add(str(item.get("name", "")))
    return keys


def open_order_statuses():
    return {"created", "submitting", "acked", "open", "partially_filled", "canceling"}


def terminal_order_statuses():
    return {"filled", "canceled", "partially_canceled", "rejected", "expired"}


def to_decimal(value, default="0"):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def resolve_runtime_path(path):
    if not path:
        return ORDERS_PATH
    if path.startswith("postgres://") or path.startswith("postgresql://") or path.startswith("sqlite://"):
        return path
    if os.path.isabs(path):
        return path
    return os.path.join(ROOT, path)


def configured_order_store_path():
    try:
        config = read_config()
    except Exception:
        return ORDERS_PATH
    return resolve_runtime_path(config.get("order_store_path") or ORDERS_PATH)


def configured_runtime_command_path():
    try:
        config = read_config()
    except Exception:
        return RUNTIME_COMMANDS_PATH
    return resolve_runtime_path(config.get("runtime_command_path") or RUNTIME_COMMANDS_PATH)


def order_store_kind(path):
    lower = str(path).lower()
    if lower.startswith("postgres://") or lower.startswith("postgresql://"):
        return "postgres"
    if lower.startswith("sqlite://") or lower.endswith(".db") or lower.endswith(".sqlite") or lower.endswith(".sqlite3"):
        return "sqlite"
    return "json"


def read_order_rows():
    path = configured_order_store_path()
    if order_store_kind(path) == "json":
        if not os.path.exists(path):
            return [], path
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("orders", []), path
    store = build_order_store(path)
    return [order.to_dict() for order in store.load()], path


def parse_event_log():
    if not os.path.exists(EVENTS_PATH):
        return []
    events = []
    with open(EVENTS_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def default_exchange_accounts():
    return {
        "accounts": [
            {
                "id": "bitmart-paper-main",
                "exchange": "bitmart",
                "account_name": "BitMart Paper Main",
                "mode": "paper",
                "rest_endpoint": "https://api-cloud.bitmart.com",
                "public_ws_endpoint": "wss://ws-manager-compress.bitmart.com/api?protocol=1.1",
                "private_ws_endpoint": "wss://ws-manager-compress.bitmart.com/user?protocol=1.1",
                "read_only": True,
                "allow_order_submission": False,
                "api_key_configured": False,
                "api_key_last4": "",
                "api_secret_configured": False,
                "memo_configured": False,
                "no_withdraw_ack": False,
                "ip_whitelist_ack": False,
                "created_at_ms": 0,
                "updated_at_ms": 0,
            }
        ]
    }


def connection_status(account):
    endpoint_ok = bool(account.get("rest_endpoint"))
    public_ws_ok = bool(account.get("public_ws_endpoint"))
    private_ws_ok = bool(account.get("private_ws_endpoint"))
    private_auth_ok = bool(account.get("api_key_configured") and account.get("api_secret_configured"))
    if account.get("mode") == "paper":
        private_auth_ok = True
    return {
        "rest": "ok" if endpoint_ok else "missing",
        "public_ws": "ok" if public_ws_ok else "missing",
        "private_ws": "ok" if private_ws_ok and private_auth_ok else "needs_key",
        "can_live_order": bool(
            account.get("allow_order_submission")
            and account.get("api_key_configured")
            and account.get("api_secret_configured")
            and account.get("no_withdraw_ack")
            and account.get("ip_whitelist_ack")
        ),
    }


def exchange_payload():
    data = read_json_file(EXCHANGES_PATH, default_exchange_accounts())
    accounts = []
    for account in data.get("accounts", []):
        safe = dict(account)
        safe["connection"] = connection_status(account)
        safe.pop("api_secret", None)
        safe.pop("api_key", None)
        safe.pop("memo", None)
        accounts.append(safe)
    return {
        "accounts": accounts,
        "summary": {
            "total": len(accounts),
            "connected": len([item for item in accounts if item["connection"]["rest"] == "ok"]),
            "order_enabled": len([item for item in accounts if item["connection"]["can_live_order"]]),
        },
    }


def save_exchange_account(body):
    data = read_json_file(EXCHANGES_PATH, default_exchange_accounts())
    accounts = data.setdefault("accounts", [])
    exchange = str(body.get("exchange", "bitmart")).lower()
    account_name = str(body.get("account_name") or "BitMart Main")
    mode = str(body.get("mode") or "paper")
    account_id = str(body.get("id") or "{0}-{1}-{2}".format(exchange, slug(account_name), mode))
    existing = next((item for item in accounts if item.get("id") == account_id), {})
    api_key = str(body.get("api_key") or "")
    api_secret = str(body.get("api_secret") or "")
    memo = str(body.get("memo") or "")
    item = {
        "id": account_id,
        "exchange": exchange,
        "account_name": account_name,
        "mode": mode,
        "rest_endpoint": str(body.get("rest_endpoint") or existing.get("rest_endpoint") or ""),
        "public_ws_endpoint": str(body.get("public_ws_endpoint") or existing.get("public_ws_endpoint") or ""),
        "private_ws_endpoint": str(body.get("private_ws_endpoint") or existing.get("private_ws_endpoint") or ""),
        "read_only": bool(body.get("read_only", existing.get("read_only", True))),
        "allow_order_submission": bool(body.get("allow_order_submission", existing.get("allow_order_submission", False))),
        "api_key_configured": bool(api_key or existing.get("api_key_configured")),
        "api_key_last4": api_key[-4:] if api_key else existing.get("api_key_last4", ""),
        "api_secret_configured": bool(api_secret or existing.get("api_secret_configured")),
        "memo_configured": bool(memo or existing.get("memo_configured")),
        "no_withdraw_ack": bool(body.get("no_withdraw_ack", existing.get("no_withdraw_ack", False))),
        "ip_whitelist_ack": bool(body.get("ip_whitelist_ack", existing.get("ip_whitelist_ack", False))),
        "created_at_ms": existing.get("created_at_ms") or now_ms(),
        "updated_at_ms": now_ms(),
    }
    replaced = False
    for idx, account in enumerate(accounts):
        if account.get("id") == account_id:
            accounts[idx] = item
            replaced = True
            break
    if not replaced:
        accounts.append(item)
    write_json_file(EXCHANGES_PATH, data)
    return {"ok": True, "account": {**item, "connection": connection_status(item)}, "exchanges": exchange_payload()}


def test_exchange_account(body):
    account_id = body.get("id")
    account = {}
    for item in exchange_payload().get("accounts", []):
        if item.get("id") == account_id:
            account = item
            break
    if not account:
        account = body
    status = connection_status(account)
    checks = [
        {"name": "REST endpoint", "passed": status["rest"] == "ok", "message": status["rest"]},
        {"name": "Public WebSocket", "passed": status["public_ws"] == "ok", "message": status["public_ws"]},
        {"name": "Private WebSocket", "passed": status["private_ws"] in {"ok", "needs_key"}, "message": status["private_ws"]},
        {
            "name": "Live order gate",
            "passed": bool(account.get("mode") != "live" or status["can_live_order"]),
            "message": "ready" if status["can_live_order"] else "locked",
        },
    ]
    return {
        "ok": all(item["passed"] for item in checks),
        "dry_run": True,
        "message": "local validation only; no outbound network call",
        "checks": checks,
    }


def save_symbol(body):
    config = read_config()
    symbol = str(body["symbol"]).upper()
    config.setdefault("symbols", [])
    if symbol not in config["symbols"]:
        config["symbols"].append(symbol)
    config.setdefault("market_rules", {})[symbol] = {
        "base": str(body["base"]).upper(),
        "quote": str(body["quote"]).upper(),
        "price_increment": str(body["price_increment"]),
        "size_increment": str(body["size_increment"]),
        "base_min_size": str(body["base_min_size"]),
        "min_notional": str(body["min_notional"]),
    }
    paper = config.setdefault("paper", {})
    initial_prices = paper.setdefault("initial_prices", {})
    initial_price = str(body.get("initial_price") or initial_prices.get(symbol) or "1")
    initial_prices[symbol] = initial_price
    write_config(config)
    return {"ok": True, "symbol": symbol, "config": config, "audit": audit_dict(), "symbols": symbol_payload()}


def delete_symbol(body):
    config = read_config()
    symbol = str(body["symbol"]).upper()
    existing_symbols = config.get("symbols", [])
    removed = symbol in existing_symbols
    config["symbols"] = [item for item in existing_symbols if item != symbol]
    config.setdefault("market_rules", {}).pop(symbol, None)
    config.setdefault("paper", {}).setdefault("initial_prices", {}).pop(symbol, None)
    strategies = config.get("strategies", [])
    removed_strategies = [item for item in strategies if item.get("symbol") == symbol]
    config["strategies"] = [item for item in strategies if item.get("symbol") != symbol]
    write_config(config)

    states_payload = read_json_file(STRATEGY_STATE_PATH, {"states": {}})
    removed_keys = {strategy_key(item) for item in removed_strategies}
    states_payload["states"] = {
        key: value
        for key, value in states_payload.get("states", {}).items()
        if key not in removed_keys and not key.endswith(":{0}".format(symbol))
    }
    write_json_file(STRATEGY_STATE_PATH, states_payload)
    return {
        "ok": True,
        "symbol": symbol,
        "removed": removed,
        "removed_strategies": removed_strategies,
        "config": config,
        "audit": audit_dict(),
        "symbols": symbol_payload(),
    }


def symbol_payload():
    config = read_config()
    orders = order_payload().get("orders", [])
    symbols = []
    for symbol in config.get("symbols", []):
        rule = dict(config.get("market_rules", {}).get(symbol, {}))
        history = market_history_payload(symbol=symbol, limit=1)
        latest_price = history["points"][-1]["price"] if history["points"] else None
        initial_price = config.get("paper", {}).get("initial_prices", {}).get(symbol)
        symbols.append(
            {
                "symbol": symbol,
                "exchange": config.get("exchange", "paper"),
                "enabled": True,
                "latest_price": latest_price,
                "initial_price": initial_price,
                "rule": rule,
                "strategy_count": len([item for item in config.get("strategies", []) if item.get("symbol") == symbol]),
                "order_count": len([item for item in orders if item.get("symbol") == symbol]),
            }
        )
    return {"symbols": symbols, "market_rules": config.get("market_rules", {})}


def order_matches_strategy(order, item):
    return order.get("strategy") in strategy_order_keys(item)


def fill_matches_strategy(fill, item):
    return fill.get("strategy") in strategy_order_keys(item)


def strategy_metrics(item, orders, fills, config):
    matched_orders = [order for order in orders if order_matches_strategy(order, item)]
    matched_fills = [fill for fill in fills if fill_matches_strategy(fill, item)]
    open_orders = [order for order in matched_orders if order.get("status") in open_order_statuses()]
    unknown_orders = [order for order in matched_orders if order.get("status") == "unknown"]
    open_notional = Decimal("0")
    for order in open_orders:
        price = to_decimal(order.get("price"))
        size = to_decimal(order.get("size"))
        filled = to_decimal(order.get("filled_size"))
        remaining = max(Decimal("0"), size - filled)
        open_notional += price * remaining

    buy_base = Decimal("0")
    sell_base = Decimal("0")
    buy_quote = Decimal("0")
    sell_quote = Decimal("0")
    fees = Decimal("0")
    for fill in matched_fills:
        price = to_decimal(fill.get("price"))
        size = to_decimal(fill.get("size"))
        quote = price * size
        fees += to_decimal(fill.get("fee"))
        if fill.get("side") == "buy":
            buy_base += size
            buy_quote += quote
        else:
            sell_base += size
            sell_quote += quote

    risk = config.get("risk", {})
    key = strategy_key(item)
    name = str(item.get("name", ""))
    return {
        "open_orders": len(open_orders),
        "unknown_orders": len(unknown_orders),
        "total_orders": len(matched_orders),
        "fills": len(matched_fills),
        "open_notional": str(open_notional.quantize(Decimal("0.00000001"))) if open_notional else "0",
        "filled_base": str((buy_base + sell_base).normalize()) if (buy_base + sell_base) else "0",
        "filled_quote": str((buy_quote + sell_quote).quantize(Decimal("0.00000001"))) if (buy_quote + sell_quote) else "0",
        "net_base": str((buy_base - sell_base).normalize()) if (buy_base - sell_base) else "0",
        "cashflow_quote": str((sell_quote - buy_quote - fees).quantize(Decimal("0.00000001"))) if (sell_quote or buy_quote or fees) else "0",
        "risk_limits": {
            "max_order_value_usdt": str(
                risk.get("per_strategy_max_order_value_usdt", {}).get(key)
                or risk.get("per_strategy_max_order_value_usdt", {}).get(name)
                or risk.get("max_order_value_usdt", "--")
            ),
            "max_open_orders": str(
                risk.get("per_strategy_max_open_orders", {}).get(key)
                or risk.get("per_strategy_max_open_orders", {}).get(name)
                or risk.get("max_open_orders", "--")
            ),
            "max_open_value_usdt": str(
                risk.get("per_strategy_max_open_value_usdt", {}).get(key)
                or risk.get("per_strategy_max_open_value_usdt", {}).get(name)
                or risk.get("max_total_open_value_usdt", "--")
            ),
        },
    }


def strategy_payload():
    config = read_config()
    states = read_json_file(STRATEGY_STATE_PATH, {"states": {}}).get("states", {})
    orders = order_payload().get("orders", [])
    fills = fill_payload().get("fills", [])
    strategies = []
    for item in config.get("strategies", []):
        key = strategy_key(item)
        order_keys = strategy_order_keys(item)
        status = states.get(key, {}).get("status")
        if not status:
            status = "configured" if item.get("enabled") else "disabled"
        strategies.append(
            {
                "key": key,
                "id": item.get("id", ""),
                "name": item.get("name"),
                "symbol": item.get("symbol"),
                "enabled": bool(item.get("enabled")),
                "status": status,
                "mode": config.get("trading_mode", "paper"),
                "params": item.get("params", {}),
                "metrics": strategy_metrics(item, orders, fills, config),
                "open_orders": len(
                    [
                        order
                        for order in orders
                        if order.get("strategy") in order_keys
                        and order.get("status") in open_order_statuses()
                    ]
                ),
                "fills": len([fill for fill in fills if fill.get("strategy") in order_keys]),
            }
        )
    return {"strategies": strategies, "states": states}


def strategy_detail_payload(key):
    config = read_config()
    strategies = config.get("strategies", [])
    target = next((item for item in strategies if strategy_key(item) == key), None)
    if target is None:
        return {"ok": False, "error": "strategy not found", "key": key}
    states = read_json_file(STRATEGY_STATE_PATH, {"states": {}}).get("states", {})
    orders = [order for order in order_payload().get("orders", []) if order_matches_strategy(order, target)]
    fills = [fill for fill in fill_payload().get("fills", []) if fill_matches_strategy(fill, target)]
    detail = {
        "key": strategy_key(target),
        "id": target.get("id", ""),
        "name": target.get("name"),
        "symbol": target.get("symbol"),
        "enabled": bool(target.get("enabled")),
        "status": states.get(strategy_key(target), {}).get("status") or ("configured" if target.get("enabled") else "disabled"),
        "mode": config.get("trading_mode", "paper"),
        "params": target.get("params", {}),
        "metrics": strategy_metrics(target, orders, fills, config),
        "orders": orders[-80:],
        "fills": fills[-80:],
        "cancel_plan": cancel_plan(strategy=strategy_key(target)),
    }
    return {"ok": True, "strategy": detail}


def delete_strategy(body):
    key = str(body.get("key") or body.get("id") or "").strip()
    name = str(body.get("name") or "")
    symbol = str(body.get("symbol") or "").upper()
    force = bool(body.get("force", False))
    if not key and name and symbol:
        key = "{0}:{1}".format(name, symbol)
    if not key:
        return {"ok": False, "error": "strategy key is required"}

    config = read_config()
    strategies = config.get("strategies", [])
    target = next((item for item in strategies if strategy_key(item) == key), None)
    if target is None:
        return {"ok": False, "error": "strategy not found", "key": key}

    order_keys = strategy_order_keys(target)
    open_orders = [
        order
        for order in order_payload().get("orders", [])
        if order.get("strategy") in order_keys and order.get("status") in open_order_statuses()
    ]
    if open_orders and not force:
        return {
            "ok": False,
            "error": "strategy has open orders; cancel them before deletion",
            "key": key,
            "open_orders": len(open_orders),
        }

    config["strategies"] = [item for item in strategies if strategy_key(item) != key]
    write_config(config)

    states_payload = read_json_file(STRATEGY_STATE_PATH, {"states": {}})
    states_payload["states"] = {
        state_key: value for state_key, value in states_payload.get("states", {}).items() if state_key != key
    }
    write_json_file(STRATEGY_STATE_PATH, states_payload)

    return {
        "ok": True,
        "key": key,
        "removed_strategy": target,
        "config": config,
        "audit": audit_dict(),
        "strategies": strategy_payload(),
    }


def audit_dict():
    report = build_config_audit(CONFIG_PATH)
    return {
        "path": report.path,
        "sha256": report.sha256,
        "trading_mode": report.trading_mode,
        "exchange": report.exchange,
        "symbols": report.symbols,
        "enabled_strategies": report.enabled_strategies,
        "risk_limits": report.risk_limits,
    }


def order_payload():
    try:
        orders, path = read_order_rows()
    except Exception as exc:
        return {
            "orders": [],
            "summary": {"total": 0, "open": 0, "unknown": 0, "terminal": 0},
            "store": {"path": configured_order_store_path(), "type": "error"},
            "error": str(exc),
        }
    open_statuses = open_order_statuses()
    terminal_statuses = terminal_order_statuses()
    return {
        "orders": orders,
        "summary": {
            "total": len(orders),
            "open": len([order for order in orders if order.get("status") in open_statuses]),
            "unknown": len([order for order in orders if order.get("status") == "unknown"]),
            "terminal": len([order for order in orders if order.get("status") in terminal_statuses]),
        },
        "store": {"path": path, "type": order_store_kind(path)},
    }


def remote_order_payload(fetcher=None):
    config = read_config()
    mode = str(config.get("trading_mode", "paper"))
    if mode not in {"live_read_only", "live_dry_run", "live"}:
        return remote_order_disabled("not_live_mode", "remote order sync requires live_read_only, live_dry_run, or live mode")
    try:
        settings = AppSettings.from_file(CONFIG_PATH)
    except Exception as exc:
        return remote_order_disabled("config_error", str(exc))
    if not settings.bitmart.present:
        return remote_order_disabled("credentials_missing", "BITMART_API_KEY/SECRET/MEMO are required for remote read-only sync")
    try:
        if fetcher is None:
            updates = asyncio.run(fetch_bitmart_open_orders(settings))
        else:
            updates = fetcher(settings)
    except Exception as exc:
        return {
            "orders": [],
            "summary": {"total": 0, "open": 0, "unknown": 0, "terminal": 0},
            "source": "remote",
            "status": "error",
            "message": str(exc),
        }
    orders = [order_update_row(update) for update in updates]
    return {
        "orders": orders,
        "summary": order_summary(orders),
        "source": "remote",
        "status": "ok",
        "message": "remote open orders queried from BitMart read-only API",
    }


def remote_order_disabled(status, message):
    return {
        "orders": [],
        "summary": {"total": 0, "open": 0, "unknown": 0, "terminal": 0},
        "source": "remote",
        "status": status,
        "message": message,
    }


async def fetch_bitmart_open_orders(settings):
    gateway = BitMartRestGateway(settings.bitmart)
    rows = []
    for symbol in settings.symbols:
        rows.extend(await gateway.get_open_orders(symbol))
    return rows


def order_update_row(update):
    data = to_jsonable(update)
    data["status"] = update.status.value
    data["side"] = update.side.value if update.side else data.get("side")
    data["strategy"] = data.get("strategy") or "--"
    return data


def order_summary(orders):
    open_statuses = open_order_statuses()
    terminal_statuses = terminal_order_statuses()
    return {
        "total": len(orders),
        "open": len([order for order in orders if order.get("status") in open_statuses]),
        "unknown": len([order for order in orders if order.get("status") == "unknown"]),
        "terminal": len([order for order in orders if order.get("status") in terminal_statuses]),
    }


def reconcile_payload():
    local = order_payload()
    remote = remote_order_payload()
    open_local = [order for order in local.get("orders", []) if order.get("status") in open_order_statuses()]
    diffs = build_reconcile_diffs(local.get("orders", []), remote.get("orders", []), remote.get("status", "ok"))
    return {
        "ok": True,
        "dry_run": True,
        "local_open": len(open_local),
        "remote_open": len(remote.get("orders", [])),
        "unknown_gate": any(item.get("severity") == "critical" for item in diffs),
        "diffs": diffs,
    }


def reconcile_key(order):
    return order.get("client_order_id") or ("exchange:{0}".format(order.get("exchange_order_id")) if order.get("exchange_order_id") else "")


def build_reconcile_diffs(local_orders, remote_orders, remote_status="ok"):
    diffs = []
    if remote_status != "ok":
        diffs.append(
            {
                "type": "remote_sync_unavailable",
                "severity": "info",
                "message": "remote order sync unavailable: {0}".format(remote_status),
            }
        )
    local_open = {reconcile_key(order): order for order in local_orders if order.get("status") in open_order_statuses() and reconcile_key(order)}
    remote_open = {reconcile_key(order): order for order in remote_orders if order.get("status") in open_order_statuses() and reconcile_key(order)}
    for key, order in sorted(local_open.items()):
        if key not in remote_open and remote_status == "ok":
            diffs.append(
                {
                    "type": "local_open_missing_remote",
                    "severity": "critical",
                    "client_order_id": key,
                    "symbol": order.get("symbol"),
                    "message": "local open order is missing remotely; runtime reconciliation will mark UNKNOWN and block new orders",
                }
            )
    for key, order in sorted(remote_open.items()):
        if key not in local_open:
            diffs.append(
                {
                    "type": "remote_open_orphan",
                    "severity": "critical",
                    "client_order_id": key,
                    "symbol": order.get("symbol"),
                    "message": "remote open order is not in local OMS; import as UNKNOWN before allowing new orders",
                }
            )
    for key, local_order in sorted(local_open.items()):
        remote_order = remote_open.get(key)
        if remote_order and local_order.get("status") != remote_order.get("status"):
            diffs.append(
                {
                    "type": "status_mismatch",
                    "severity": "warn",
                    "client_order_id": key,
                    "symbol": local_order.get("symbol"),
                    "message": "local status {0}, remote status {1}".format(local_order.get("status"), remote_order.get("status")),
                }
            )
    for order in local_orders:
        if order.get("status") == "unknown":
            diffs.append(
                {
                    "type": "local_unknown_order",
                    "severity": "critical",
                    "client_order_id": reconcile_key(order),
                    "symbol": order.get("symbol"),
                    "message": "UNKNOWN order present; risk engine rejects new place/cancel intents until repaired",
                }
            )
    if not diffs:
        diffs.append({"type": "matched", "severity": "info", "message": "local and remote open orders are aligned"})
    return diffs


def market_history_payload(symbol=None, limit=160):
    config = read_config()
    selected_symbol = symbol or (config.get("symbols") or ["BTC_USDT"])[0]
    points = []
    for event in parse_event_log():
        if event.get("type") != "market.snapshot":
            continue
        payload = event.get("payload", {})
        if payload.get("symbol") != selected_symbol:
            continue
        price = payload.get("last")
        if price is None:
            bid = to_decimal(payload.get("bid"))
            ask = to_decimal(payload.get("ask"))
            if bid > 0 and ask > 0:
                price = str((bid + ask) / Decimal("2"))
        if price is None:
            continue
        points.append(
            {
                "ts": int(payload.get("timestamp_ms") or event.get("ts") or 0),
                "price": float(to_decimal(price)),
                "bid": float(to_decimal(payload.get("bid"))) if payload.get("bid") is not None else None,
                "ask": float(to_decimal(payload.get("ask"))) if payload.get("ask") is not None else None,
            }
        )
    if not points:
        initial = to_decimal(config.get("paper", {}).get("initial_prices", {}).get(selected_symbol, "0"))
        if initial > 0:
            base_ts = now_ms() - 5 * 60 * 1000
            points = [
                {"ts": base_ts + idx * 30 * 1000, "price": float(initial + Decimal(idx - 5) * Decimal("3")), "bid": None, "ask": None}
                for idx in range(10)
            ]
    points = points[-max(1, min(limit, 500)) :]
    latest = points[-1] if points else None
    return {"symbol": selected_symbol, "points": points, "latest": latest}


def fill_payload():
    orders = {order.get("client_order_id"): order for order in order_payload().get("orders", [])}
    fills = []
    total_quote = Decimal("0")
    total_base = Decimal("0")
    for event in parse_event_log():
        if event.get("type") != "order.fill":
            continue
        payload = dict(event.get("payload", {}))
        order = orders.get(payload.get("client_order_id"), {})
        payload["strategy"] = order.get("strategy", payload.get("strategy", "--"))
        payload["level"] = order.get("level", payload.get("level"))
        price = to_decimal(payload.get("price"))
        size = to_decimal(payload.get("size"))
        total_quote += price * size
        total_base += size
        fills.append(payload)
    return {
        "fills": fills[-200:],
        "summary": {
            "total": len(fills),
            "base_volume": str(total_base.normalize()) if total_base else "0",
            "quote_volume": str(total_quote.quantize(Decimal("0.00000001"))) if total_quote else "0",
        },
    }


def inventory_payload():
    latest_balances = []
    latest_pnl = {}
    for event in parse_event_log():
        if event.get("type") == "account.balances":
            latest_balances = event.get("payload", [])
        elif event.get("type") == "account.pnl":
            latest_pnl = event.get("payload", {})
    return {"balances": latest_balances, "pnl": latest_pnl}


def risk_payload():
    config = read_config()
    state = read_json_file(RISK_STATE_PATH, {"safe_mode": False, "reason": "", "updated_at_ms": 0})
    security = config.get("security", {})
    orders = order_payload()
    unknown_orders = [order for order in orders.get("orders", []) if order.get("status") == "unknown"]
    live_ready = bool(
        config.get("enable_order_submission")
        and security.get("api_key_no_withdraw_permission_ack")
        and security.get("api_key_ip_whitelist_ack")
        and security.get("production_runbook_ack")
    )
    return {
        "risk": config.get("risk", {}),
        "state": state,
        "security": security,
        "live_ready": live_ready,
        "unknown_gate": {
            "blocked": bool(unknown_orders),
            "count": len(unknown_orders),
            "message": "UNKNOWN orders block new order placement" if unknown_orders else "no UNKNOWN orders",
        },
        "checks": [
            {
                "name": "UNKNOWN order gate",
                "passed": not unknown_orders,
                "message": "blocked {0}".format(len(unknown_orders)) if unknown_orders else "clear",
            },
            {
                "name": "API key no withdraw permission",
                "passed": bool(security.get("api_key_no_withdraw_permission_ack")),
                "message": "ack" if security.get("api_key_no_withdraw_permission_ack") else "missing",
            },
            {
                "name": "API key IP whitelist",
                "passed": bool(security.get("api_key_ip_whitelist_ack")),
                "message": "ack" if security.get("api_key_ip_whitelist_ack") else "missing",
            },
            {
                "name": "Production runbook",
                "passed": bool(security.get("production_runbook_ack")),
                "message": "ack" if security.get("production_runbook_ack") else "missing",
            },
        ],
    }


def update_strategy_state(body):
    key = str(body.get("key") or body.get("id") or "").strip()
    name = str(body.get("name") or "")
    symbol = str(body.get("symbol") or "").upper()
    action = str(body.get("action") or "pause").lower()
    if not key:
        if not name or not symbol:
            return {"ok": False, "error": "strategy key or name and symbol are required"}
        key = "{0}:{1}".format(name, symbol)
    status = "running" if action in {"start", "running"} else "paused"
    payload = read_json_file(STRATEGY_STATE_PATH, {"states": {}})
    payload.setdefault("states", {})[key] = {"status": status, "updated_at_ms": now_ms()}
    write_json_file(STRATEGY_STATE_PATH, payload)
    return {"ok": True, "key": key, "status": status, "strategies": strategy_payload()}


def stop_cancel_strategy(body):
    key = str(body.get("key") or body.get("id") or "").strip()
    name = str(body.get("name") or "")
    symbol = str(body.get("symbol") or "").upper()
    execute = bool(body.get("execute", False))
    if not key and name and symbol:
        key = "{0}:{1}".format(name, symbol)
    if not key:
        return {"ok": False, "error": "strategy key is required"}

    config = read_config()
    target = next((item for item in config.get("strategies", []) if strategy_key(item) == key), None)
    if target is None:
        return {"ok": False, "error": "strategy not found", "key": key}

    state_result = update_strategy_state({"key": key, "action": "pause"})
    plan = cancel_plan(strategy=key)
    result = {
        "ok": True,
        "key": key,
        "status": state_result.get("status"),
        "strategies": state_result.get("strategies"),
        "cancel_plan": plan,
        "executed": False,
        "message": "strategy paused; cancel plan generated",
    }
    if not execute:
        return result

    mode = str(config.get("trading_mode", "paper"))
    if mode != "live" or not config.get("enable_order_submission"):
        result["message"] = "live cancel execution is locked outside live mode with enable_order_submission=true"
        return result
    try:
        settings = AppSettings.from_file(CONFIG_PATH)
    except Exception as exc:
        result["message"] = str(exc)
        return result
    requests = list(plan.get("requests", []))
    if not requests:
        result["executed"] = True
        result["message"] = "strategy paused; no open orders to cancel"
        return result
    command = queue_runtime_command(
        {
            "type": "stop_cancel_strategy",
            "strategy": key,
            "strategy_aliases": sorted(strategy_order_keys(target)),
            "requests": requests,
            "source": "admin",
            "mode": settings.trading_mode.value,
        }
    )
    result["queued"] = True
    result["command_id"] = command["id"]
    result["message"] = "strategy paused; live cancel command queued for trading engine"
    return result


def queue_runtime_command(command):
    path = configured_runtime_command_path()
    payload = read_json_file(path, {"commands": []})
    commands = payload.setdefault("commands", [])
    if not isinstance(commands, list):
        commands = []
        payload["commands"] = commands
    command = dict(command)
    command["id"] = "cmd-{0}-{1}".format(now_ms(), secrets.token_hex(4))
    command["status"] = "pending"
    command["created_at_ms"] = now_ms()
    commands.append(command)
    write_json_file(path, payload)
    return command


def update_kill_switch(body):
    enabled = bool(body.get("enabled", True))
    reason = str(body.get("reason") or ("manual kill switch" if enabled else "manual resume"))
    state = {"safe_mode": enabled, "reason": reason, "updated_at_ms": now_ms()}
    write_json_file(RISK_STATE_PATH, state)
    return {"ok": True, "state": state, "risk": risk_payload()}


def cancel_plan(symbol=None, strategy=None):
    payload = order_payload()
    open_statuses = {"created", "submitting", "acked", "open", "partially_filled", "canceling"}
    strategy_key_value = str(strategy or "").strip()
    strategy_keys = {strategy_key_value} if strategy_key_value else set()
    if strategy_key_value:
        target = next((item for item in read_config().get("strategies", []) if strategy_key(item) == strategy_key_value), None)
        if target is not None:
            strategy_keys = strategy_order_keys(target)
    orders = [
        order
        for order in payload["orders"]
        if order.get("status") in open_statuses
        and (not symbol or order.get("symbol") == symbol)
        and (not strategy_key_value or order.get("strategy") in strategy_keys)
    ]
    return {
        "ok": True,
        "dry_run": True,
        "strategy": strategy_key_value or None,
        "symbol": symbol,
        "message": "cancel plan generated only; no exchange request sent",
        "requests": [
            {
                "symbol": order.get("symbol"),
                "client_order_id": order.get("client_order_id"),
                "exchange_order_id": order.get("exchange_order_id"),
                "strategy": order.get("strategy"),
            }
            for order in orders
        ],
    }


def event_summary():
    if not os.path.exists(EVENTS_PATH):
        return {}
    return EventLogReplay(EVENTS_PATH).count_by_type()


def main():
    port = int(os.environ.get("ADMIN_PORT", "8765"))
    host = os.environ.get("ADMIN_HOST", "127.0.0.1")
    security = admin_security()
    server = ThreadingHTTPServer((host, port), AdminHandler)
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    print("Admin server running at http://{0}:{1}/".format(display_host, port), flush=True)
    if os.path.exists(ADMIN_TOKEN_PATH) and not os.environ.get("ADMIN_TOKEN"):
        print("Local admin token file: {0}".format(ADMIN_TOKEN_PATH), flush=True)
    if os.path.exists(ADMIN_USERS_PATH) and not os.environ.get("ADMIN_USERNAME"):
        print("Local admin users file: {0}".format(ADMIN_USERS_PATH), flush=True)
    print("Admin audit log: {0}".format(security.audit_path), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
