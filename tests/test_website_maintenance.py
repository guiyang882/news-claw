"""Layer-specific website reloads must remain explicit and health-gated."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from workflows import website_maintenance as website


class WebsiteMaintenanceTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.config = json.loads((root / "config/templates/website-maintenance.json").read_text())
        self.invoke = Mock()
        self.probe = Mock(return_value={"application": {"status": 200}, "nginx": {"status": 200}})

    def run_action(self, action, execute=False):
        return website.run(self.config, action, execute=execute, invoke=self.invoke, probe=self.probe)

    def test_reload_preview_performs_no_commands_or_requests(self):
        self.assertEqual(self.run_action("reload-application")["business_status"], "preview")
        self.invoke.assert_not_called()
        self.probe.assert_not_called()

    def test_application_reload_signals_only_gunicorn_master(self):
        result = self.run_action("reload-application", True)
        commands = [call.args[0] for call in self.invoke.call_args_list]
        self.assertEqual(commands[-1], ["systemctl", "kill", "--kill-whom=main", "--signal=HUP", "quant-web.service"])
        self.assertFalse(any("restart" in argv or "caddy.service" in argv for argv in commands))
        self.assertEqual(self.probe.call_count, 2)
        self.assertEqual(result["business_status"], "reloaded")

    def test_invalid_nginx_config_stops_before_reload(self):
        self.invoke.side_effect = [None, RuntimeError("invalid nginx config")]
        with self.assertRaisesRegex(RuntimeError, "invalid nginx config"):
            self.run_action("reload-proxy", True)
        self.assertEqual(self.invoke.call_count, 2)
        self.probe.assert_not_called()

    def test_unhealthy_site_stops_before_reload(self):
        self.probe.side_effect = RuntimeError("unhealthy upstream")
        with self.assertRaisesRegex(RuntimeError, "unhealthy upstream"):
            self.run_action("reload-proxy", True)
        self.assertEqual(self.invoke.call_count, 2)

    def test_proxy_reload_does_not_restart_application(self):
        self.run_action("reload-proxy", True)
        commands = [call.args[0] for call in self.invoke.call_args_list]
        self.assertEqual(commands[-1], ["systemctl", "reload", "nginx.service"])
        self.assertFalse(any("kill" in argv or "restart" in argv for argv in commands))

    def test_plain_check_never_reloads_services(self):
        self.assertEqual(self.run_action("check")["business_status"], "healthy")
        self.assertEqual(self.invoke.call_count, 2)
        self.assertEqual(self.probe.call_count, 1)

    def test_content_publication_cannot_select_a_restart_policy(self):
        self.config["workflow"]["website_runtime"]["content_update_action"] = "restart"
        with self.assertRaises(ValueError):
            self.run_action("check")
        self.invoke.assert_not_called()

    def test_https_connects_locally_with_real_domain_certificate_validation(self):
        connection = website.LocalHTTPS("growthyoung.com", 443, timeout=10)
        self.assertTrue(connection._context.check_hostname)
        with patch("socket.create_connection") as connect, patch.object(connection._context, "wrap_socket") as wrap:
            connection.connect()
        connect.assert_called_once_with(("127.0.0.1", 443), timeout=10)
        wrap.assert_called_once_with(connect.return_value, server_hostname="growthyoung.com")

    def test_healthy_http_code_without_health_status_is_rejected(self):
        response = Mock(status=200)
        response.read.return_value = b'[]'
        with patch("http.client.HTTPConnection") as connection:
            connection.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(RuntimeError, "invalid health result"):
                website.health_probe(self.config["workflow"]["website_runtime"])
        connection.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
