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
        self.probe = Mock(return_value={"content": {"status": 200}, "frontend": {"status": 200}, "nginx": {"status": 200}})

    def run_action(self, action, execute=False):
        return website.run(self.config, action, execute=execute, invoke=self.invoke, probe=self.probe)

    def test_reload_preview_performs_no_commands_or_requests(self):
        self.assertEqual(self.run_action("reload-content")["business_status"], "preview")
        self.invoke.assert_not_called()
        self.probe.assert_not_called()

    def test_content_reload_signals_only_gunicorn_master(self):
        result = self.run_action("reload-content", True)
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

    def test_frontend_restart_targets_node_without_signaling_python(self):
        self.assertEqual(self.run_action("restart-frontend", True)["business_status"], "restarted")
        self.assertEqual(self.invoke.call_args_list[-1].args[0], ["systemctl", "restart", "quant-next-web.service"])
        self.assertNotIn("kill", self.invoke.call_args_list[-1].args[0])

    def test_obsolete_application_action_is_rejected_before_any_command(self):
        with self.assertRaisesRegex(ValueError, "obsolete"):
            self.run_action("reload-application", True)
        self.invoke.assert_not_called()

    def test_in_place_frontend_build_policy_is_rejected(self):
        self.config["workflow"]["website_runtime"]["frontend_deployment"]["build_in_running_directory"] = True
        with self.assertRaisesRegex(ValueError, "outside"):
            self.run_action("check")

    def test_frontend_restart_requires_all_three_services(self):
        self.run_action("restart-frontend", True)
        self.assertEqual(self.invoke.call_args_list[0].args[0], ["systemctl", "is-active", "--quiet", "quant-web.service", "quant-next-web.service", "nginx.service"])

    def test_readiness_polling_is_bounded_and_only_after_mutation(self):
        self.probe.side_effect = [self.probe.return_value, OSError("Node starting"), self.probe.return_value]
        with patch("time.sleep"):
            self.assertEqual(self.run_action("restart-frontend", True)["business_status"], "restarted")
        self.assertEqual(self.probe.call_count, 3)

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

    def test_backend_health_alone_does_not_prove_frontend_works(self):
        response = Mock(status=200)
        response.read.side_effect = [b'{"status":"ok"}', b'{"status":"ok"}']
        with patch("http.client.HTTPConnection") as connection:
            connection.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(RuntimeError, "expected Next.js page"):
                website.health_probe(self.config["workflow"]["website_runtime"])

    def test_all_persisted_tasks_and_templates_describe_the_current_stack(self):
        root = Path(__file__).resolve().parents[1]
        for directory in ("tasks", "templates"):
            for path in (root / "config" / directory).glob("*.json"):
                with self.subTest(path=path.name):
                    config = json.loads(path.read_text())
                    runtime = website.settings(config)
                    self.assertEqual(runtime["frontend_service"], "quant-next-web.service")
                    self.assertNotIn("application_reload_command", runtime)

    def test_legacy_migration_preserves_website_and_model_configuration(self):
        from scripts import migrate_systemd
        from copy import deepcopy
        root = Path(__file__).resolve().parents[1]
        for task_id in ("stocks-quant-blog-compose", "stocks-quant-blog-daily-publish", "stocks-quant-market-news-analysis"):
            with self.subTest(task=task_id):
                original = json.loads((root / "config/tasks" / (task_id + ".json")).read_text())
                prepared = migrate_systemd.prepare_config(deepcopy(original), migrate_systemd.JOBS[task_id], {}, "Asia/Shanghai")
                for key in ("website_runtime", "website_delivery", "codex"):
                    if key in original["workflow"]:
                        self.assertEqual(prepared["workflow"][key], original["workflow"][key])


if __name__ == "__main__":
    unittest.main()
