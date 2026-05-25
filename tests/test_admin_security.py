import importlib.util
import json
import os
import tempfile
import unittest


def load_admin_server():
    path = os.path.join(os.getcwd(), "scripts", "admin_server.py")
    spec = importlib.util.spec_from_file_location("admin_server_security_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdminSecurityTest(unittest.TestCase):
    def setUp(self):
        self.admin = load_admin_server()
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.admin.CONFIG_PATH = os.path.join(root, "paper.json")
        self.admin.ORDERS_PATH = os.path.join(root, "orders.json")
        self.admin.EVENTS_PATH = os.path.join(root, "events.jsonl")
        self.admin.EXCHANGES_PATH = os.path.join(root, "exchanges.json")
        self.admin.STRATEGY_STATE_PATH = os.path.join(root, "strategy_state.json")
        self.admin.RISK_STATE_PATH = os.path.join(root, "risk_state.json")
        self.admin.RUNTIME_COMMANDS_PATH = os.path.join(root, "commands.json")
        self.admin.ADMIN_AUDIT_PATH = os.path.join(root, "admin_audit.jsonl")
        self.admin.ADMIN_TOKEN_PATH = os.path.join(root, "admin_token.json")
        self.admin.SECURITY = self.admin.AdminSecurity(
            tokens={
                "admin-token": {"user": "alice", "role": "admin"},
                "operator-token": {"user": "olivia", "role": "operator"},
                "viewer-token": {"user": "bob", "role": "viewer"},
            },
            audit_path=self.admin.ADMIN_AUDIT_PATH,
            token_path=self.admin.ADMIN_TOKEN_PATH,
            audit_secret="test-audit-secret",
        )
        self._write(
            self.admin.CONFIG_PATH,
            {
                "trading_mode": "paper",
                "exchange": "paper",
                "symbols": ["BTC_USDT"],
                "risk": {},
                "paper": {"initial_prices": {"BTC_USDT": "68000"}},
                "security": {},
                "strategies": [],
            },
        )
        self._write(self.admin.ORDERS_PATH, {"orders": []})

    def tearDown(self):
        self.tmp.cleanup()

    def test_authenticate_and_rbac_permissions(self):
        self.assertIsNone(self.admin.admin_security().authenticate({}))
        viewer = self.admin.admin_security().authenticate({"Authorization": "Bearer viewer-token"})
        self.assertEqual(viewer["role"], "viewer")
        self.assertFalse(self.admin.admin_security().allowed(viewer, "configure"))

        admin = self.admin.admin_security().authenticate({"Authorization": "Bearer admin-token"})
        self.assertTrue(self.admin.admin_security().allowed(admin, "configure"))
        self.assertEqual(self.admin.permission_for("POST", "/api/symbols"), "configure")

    def test_sensitive_operation_requires_confirmation_and_signed_audit(self):
        error = self.admin.confirmation_error_for("/api/risk/kill-switch", {"enabled": True})
        self.assertIn("PAUSE NEW ORDERS", error)

        admin = self.admin.admin_security().authenticate({"Authorization": "Bearer admin-token"})
        body = {"enabled": True, "confirmation": "PAUSE NEW ORDERS"}
        self.assertEqual(self.admin.confirmation_error_for("/api/risk/kill-switch", body), "")
        payload = self.admin.update_kill_switch(body)
        self.admin.admin_security().append_audit(
            admin,
            "/api/risk/kill-switch",
            body,
            payload,
            200,
        )
        self.assertTrue(payload["ok"])
        audit = self.admin.admin_security().audit_payload()
        self.assertTrue(audit["valid_chain"])
        self.assertGreaterEqual(audit["total"], 1)
        self.assertEqual(audit["events"][-1]["request"]["confirmation"], "PAUSE NEW ORDERS")

    def test_live_stop_cancel_execute_requires_trade_permission_and_stronger_confirmation(self):
        expected = self.admin.expected_confirmation(
            "/api/strategies/stop-cancel",
            {"key": "basic_mm:BTC_USDT", "execute": True},
        )
        self.assertEqual(expected, "EXECUTE LIVE CANCEL basic_mm:BTC_USDT")
        operator = self.admin.admin_security().authenticate({"Authorization": "Bearer operator-token"})
        self.assertEqual(operator["role"], "operator")
        self.assertEqual(
            self.admin.execution_permission_error_for(
                operator,
                "/api/strategies/stop-cancel",
                {"key": "basic_mm:BTC_USDT", "execute": True},
            ),
            "permission denied: trade permission required for live execution",
        )

    def test_login_redacts_token_in_audit(self):
        payload = self.admin.admin_security().login({"token": "admin-token"})
        self.assertEqual(payload["user"]["role"], "admin")
        audit = self.admin.admin_security().audit_payload()
        self.assertEqual(audit["events"][-1]["request"], {})

    def test_password_login_creates_user_session_and_audits_user(self):
        security = self.admin.AdminSecurity(
            tokens={},
            users={
                "trader-a": {
                    "username": "trader-a",
                    "password_hash": self.admin.hash_password("secret-pass"),
                    "role": "operator",
                    "active": True,
                }
            },
            audit_path=self.admin.ADMIN_AUDIT_PATH,
            token_path=self.admin.ADMIN_TOKEN_PATH,
            users_path=os.path.join(self.tmp.name, "admin_users.json"),
            audit_secret="test-audit-secret",
        )
        payload = security.login({"username": "trader-a", "password": "secret-pass"})
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["token"].startswith("sess_"))
        principal = security.authenticate({"Authorization": "Bearer {0}".format(payload["token"])})
        self.assertEqual(principal["user"], "trader-a")
        self.assertEqual(principal["role"], "operator")
        self.assertEqual(principal["auth_type"], "session")
        audit = security.audit_payload()
        self.assertTrue(audit["valid_chain"])
        self.assertEqual(audit["events"][-1]["user"], "trader-a")
        self.assertEqual(audit["events"][-1]["request"]["username"], "trader-a")
        self.assertEqual(audit["events"][-1]["request"]["password"], "***")

    def test_password_login_rejects_invalid_user_without_leaking_password(self):
        security = self.admin.AdminSecurity(
            tokens={},
            users={
                "viewer-a": {
                    "username": "viewer-a",
                    "password_hash": self.admin.hash_password("right-pass"),
                    "role": "viewer",
                    "active": True,
                }
            },
            audit_path=self.admin.ADMIN_AUDIT_PATH,
            token_path=self.admin.ADMIN_TOKEN_PATH,
            users_path=os.path.join(self.tmp.name, "admin_users.json"),
            audit_secret="test-audit-secret",
        )
        payload = security.login({"username": "viewer-a", "password": "wrong-pass"})
        self.assertFalse(payload["ok"])
        audit = security.audit_payload()
        self.assertEqual(audit["events"][-1]["user"], "anonymous")
        self.assertEqual(audit["events"][-1]["request"]["password"], "***")

    def _write(self, path, payload):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)


if __name__ == "__main__":
    unittest.main()
