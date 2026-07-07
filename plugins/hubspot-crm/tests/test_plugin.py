import importlib.util
import json
import pathlib
import sys
import types
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1]


def _install_plugin_api_stub():
    if "plugins.api" in sys.modules:
        return

    plugins_module = types.ModuleType("plugins")
    api_module = types.ModuleType("plugins.api")

    class PluginTool:
        def __init__(self, plugin_api):
            self.plugin_api = plugin_api

        @property
        def destructive_tool_names(self):
            return set()

        @property
        def background_allowed_tool_names(self):
            return set()

    class PluginAPI:
        pass

    api_module.PluginTool = PluginTool
    api_module.PluginAPI = PluginAPI
    plugins_module.api = api_module
    sys.modules["plugins"] = plugins_module
    sys.modules["plugins.api"] = api_module


def _load_module():
    _install_plugin_api_stub()
    spec = importlib.util.spec_from_file_location(
        "hubspot_crm_plugin_main",
        PLUGIN_DIR / "plugin_main.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _http_error(code):
    return urllib.error.HTTPError(
        url="https://api.hubapi.com", code=code, msg="err", hdrs=None, fp=None
    )


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))

    def test_manifest_v2_shape(self):
        self.assertEqual(self.manifest["schema_version"], 2)
        self.assertEqual(self.manifest["id"], "hubspot-crm")
        self.assertEqual(self.manifest["min_row_bot_version"], "0.0.0")

    def test_permissions_minimal(self):
        self.assertEqual(sorted(self.manifest["permissions"]), ["account", "network"])

    def test_provides_tool_and_skill(self):
        provides = self.manifest["provides"]
        self.assertEqual(provides["native_tools"][0]["id"], "hubspot_crm")
        self.assertEqual(provides["native_tools"][0]["entrypoint"], "plugin_main.py")
        self.assertEqual(provides["skills"][0]["id"], "hubspot_crm")

    def test_declares_token_secret_and_auth(self):
        self.assertIn("access_token", self.manifest["secrets"])
        self.assertEqual(self.manifest["auth"]["account"]["type"], "bearer_token")
        self.assertEqual(self.manifest["auth"]["account"]["secret"], "access_token")

    def test_health_check_requires_token(self):
        checks = self.manifest["health_checks"]
        self.assertEqual(checks[0]["type"], "required_secrets")
        self.assertIn("access_token", checks[0]["secrets"])

    def test_read_only_no_send_permissions(self):
        self.assertNotIn("external_send", self.manifest["permissions"])
        self.assertNotIn("messaging", self.manifest["permissions"])


class TestRegister(unittest.TestCase):
    def test_register_registers_all_tools(self):
        module = _load_module()
        api = MagicMock()
        module.register(api)
        self.assertEqual(api.register_tool.call_count, 5)
        names = {call.args[0].name for call in api.register_tool.call_args_list}
        self.assertEqual(
            names,
            {
                "hubspot_crm",
                "hubspot_create_record",
                "hubspot_update_record",
                "hubspot_delete_record",
                "hubspot_log_engagement",
            },
        )

    def test_read_tool_is_not_destructive(self):
        module = _load_module()
        api = MagicMock()
        read_tool = module.HubSpotCRMTool(api)
        self.assertEqual(read_tool.destructive_tool_names, set())

    def test_write_tools_are_destructive(self):
        module = _load_module()
        api = MagicMock()
        for cls, expected in [
            (module.HubSpotCreateRecordTool, "hubspot_create_record"),
            (module.HubSpotUpdateRecordTool, "hubspot_update_record"),
            (module.HubSpotDeleteRecordTool, "hubspot_delete_record"),
            (module.HubSpotLogEngagementTool, "hubspot_log_engagement"),
        ]:
            tool = cls(api)
            self.assertEqual(tool.destructive_tool_names, {expected})
            self.assertEqual(tool.name, expected)


class TestManifestDeclaresWriteTools(unittest.TestCase):
    def test_manifest_lists_all_five_native_tools(self):
        manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))
        ids = {t["id"] for t in manifest["provides"]["native_tools"]}
        self.assertEqual(
            ids,
            {
                "hubspot_crm",
                "hubspot_create_record",
                "hubspot_update_record",
                "hubspot_delete_record",
                "hubspot_log_engagement",
            },
        )


class TestQueryParser(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()

    def test_empty_query_is_help(self):
        action, _ = self.module._parse_query("", 10)
        self.assertEqual(action, "help")

    def test_search_contacts_with_count(self):
        action, params = self.module._parse_query("search_contacts jane doe 5", 10)
        self.assertEqual(action, "search")
        self.assertEqual(params["object_type"], "contacts")
        self.assertEqual(params["query"], "jane doe")
        self.assertEqual(params["count"], 5)

    def test_search_companies_default_count(self):
        action, params = self.module._parse_query("search_companies Acme", 10)
        self.assertEqual(params["object_type"], "companies")
        self.assertEqual(params["query"], "Acme")
        self.assertEqual(params["count"], 10)

    def test_list_deals_with_count(self):
        action, params = self.module._parse_query("list_deals 20", 10)
        self.assertEqual(action, "list_deals")
        self.assertEqual(params["count"], 20)

    def test_detail_deal(self):
        action, params = self.module._parse_query("deal 12045", 10)
        self.assertEqual(action, "detail")
        self.assertEqual(params["object_type"], "deals")
        self.assertEqual(params["record_id"], "12045")

    def test_bare_query_searches_contacts(self):
        action, params = self.module._parse_query("acme corp", 10)
        self.assertEqual(action, "search")
        self.assertEqual(params["object_type"], "contacts")
        self.assertEqual(params["query"], "acme corp")

    def test_missing_search_query_is_error(self):
        self.assertEqual(self.module._parse_query("search_deals", 10)[0], "error")

    def test_missing_detail_id_is_error(self):
        self.assertEqual(self.module._parse_query("contact", 10)[0], "error")

    def test_count_clamping(self):
        self.assertEqual(self.module._parse_query("search_contacts x 100", 10)[1]["count"], 30)
        self.assertEqual(self.module._parse_query("search_contacts x 0", 10)[1]["count"], 1)


class TestFormatting(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()

    def test_format_contact(self):
        result = {
            "id": "501",
            "properties": {
                "firstname": "Jane",
                "lastname": "Doe",
                "email": "jane@acme.com",
                "jobtitle": "CTO",
                "company": "Acme",
            },
        }
        text = self.module._format_contact(result, index=1)
        self.assertIn("[1] **Jane Doe**", text)
        self.assertIn("id: 501", text)
        self.assertIn("jane@acme.com", text)
        self.assertIn("CTO @ Acme", text)

    def test_format_contact_falls_back_to_email(self):
        result = {"id": "9", "properties": {"email": "x@y.com"}}
        text = self.module._format_contact(result)
        self.assertIn("**x@y.com**", text)

    def test_format_amount(self):
        self.assertEqual(self.module._format_amount("15000"), "15,000")
        self.assertEqual(self.module._format_amount("1500.5"), "1,500.50")
        self.assertEqual(self.module._format_amount(None), "None")

    def test_summarize_pipeline(self):
        deals = [
            {"properties": {"dealstage": "qualified", "amount": "1000"}},
            {"properties": {"dealstage": "qualified", "amount": "500"}},
            {"properties": {"dealstage": "closedwon", "amount": "2000"}},
        ]
        summary = self.module._summarize_pipeline(deals)
        self.assertIn("Pipeline summary", summary)
        self.assertIn("qualified: 2 deal(s), 1,500", summary)
        self.assertIn("closedwon: 1 deal(s), 2,000", summary)
        self.assertIn("Total: 3 deal(s), 3,500", summary)


class TestNetworkMocked(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()

    def test_run_search_formats_results(self):
        fake = (
            [
                {"id": "1", "properties": {"firstname": "Ada", "lastname": "L", "email": "ada@x.com"}},
                {"id": "2", "properties": {"firstname": "Bo", "email": "bo@x.com"}},
            ],
            2,
        )
        with patch.object(self.module, "_search_objects", return_value=fake):
            result = self.module._run_search("contacts", "x", 10, "pat-token")
        self.assertIn("Found 2 contacts", result)
        self.assertIn("Ada", result)
        self.assertIn("Bo", result)

    def test_run_search_no_results(self):
        with patch.object(self.module, "_search_objects", return_value=([], 0)):
            result = self.module._run_search("deals", "nothing", 10, "pat-token")
        self.assertIn("No deals found", result)

    def test_run_list_deals_includes_summary(self):
        deals = [
            {"id": "1", "properties": {"dealname": "A", "amount": "1000", "dealstage": "new"}},
            {"id": "2", "properties": {"dealname": "B", "amount": "3000", "dealstage": "new"}},
        ]
        with patch.object(self.module, "_list_deal_records", return_value=deals):
            result = self.module._run_list_deals(10, "pat-token")
        self.assertIn("Pipeline summary", result)
        self.assertIn("Total: 2 deal(s), 4,000", result)
        self.assertIn("**A**", result)

    def test_run_detail_not_found(self):
        with patch.object(self.module, "_get_record", return_value=None):
            result = self.module._run_detail("contacts", "999", "pat-token")
        self.assertIn("Could not find contact with id 999", result)


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()
        self.api = MagicMock()
        self.api.get_config.return_value = 10
        self.api.get_secret.return_value = "pat-token"
        self.tool = self.module.HubSpotCRMTool(self.api)

    def test_execute_without_token(self):
        self.api.get_secret.return_value = None
        result = self.tool.execute("search_contacts jane")
        self.assertIn("not configured", result)

    def test_execute_help(self):
        result = self.tool.execute("")
        self.assertIn("Commands", result)
        self.assertIn("search_contacts", result)

    def test_execute_routes_to_search(self):
        with patch.object(self.module, "_run_search", return_value="ok") as mock:
            result = self.tool.execute("search_contacts jane 5")
        self.assertEqual(result, "ok")
        mock.assert_called_once_with("contacts", "jane", 5, "pat-token")

    def test_execute_handles_http_401(self):
        with patch.object(self.module, "_run_search", side_effect=_http_error(401)):
            result = self.tool.execute("search_contacts jane")
        self.assertIn("401", result)

    def test_execute_handles_http_403(self):
        with patch.object(self.module, "_run_search", side_effect=_http_error(403)):
            result = self.tool.execute("search_contacts jane")
        self.assertIn("scope", result)

    def test_execute_handles_rate_limit(self):
        with patch.object(self.module, "_run_list_deals", side_effect=_http_error(429)):
            result = self.tool.execute("list_deals")
        self.assertIn("rate limit", result.lower())

    def test_execute_respects_config_count(self):
        self.api.get_config.return_value = 3
        with patch.object(self.module, "_run_search", return_value="ok") as mock:
            self.tool.execute("search_contacts jane")
        mock.assert_called_once_with("contacts", "jane", 3, "pat-token")


class TestWriteParsing(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()

    def test_parse_properties_with_quotes(self):
        props = self.module._parse_properties('dealname="Acme renewal" amount=15000 dealstage=qualified')
        self.assertEqual(props["dealname"], "Acme renewal")
        self.assertEqual(props["amount"], "15000")
        self.assertEqual(props["dealstage"], "qualified")

    def test_parse_object_and_props(self):
        obj, props = self.module._parse_object_and_props("contact email=jane@acme.com firstname=Jane")
        self.assertEqual(obj, "contact")
        self.assertEqual(props["email"], "jane@acme.com")
        self.assertEqual(props["firstname"], "Jane")

    def test_parse_object_id_props(self):
        obj, rid, props = self.module._parse_object_id_props("deal 12045 dealstage=closedwon amount=20000")
        self.assertEqual(obj, "deal")
        self.assertEqual(rid, "12045")
        self.assertEqual(props, {"dealstage": "closedwon", "amount": "20000"})

    def test_parse_engagement(self):
        parsed = self.module._parse_engagement("note deal 12045 Spoke with client about renewal")
        self.assertEqual(parsed, ("note", "deal", "12045", "Spoke with client about renewal"))

    def test_parse_engagement_too_short(self):
        self.assertIsNone(self.module._parse_engagement("note deal 12045"))


class TestWriteRunnersMocked(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()

    def test_run_create_posts_and_reports_id(self):
        with patch.object(self.module, "_api_request", return_value={"id": "9001"}) as mock:
            result = self.module._run_create("contact", {"email": "a@b.com"}, "pat-token")
        self.assertIn("Created contact (id: 9001)", result)
        method, path = mock.call_args.args[0], mock.call_args.args[1]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/crm/v3/objects/contacts")
        self.assertEqual(mock.call_args.kwargs["body"], {"properties": {"email": "a@b.com"}})

    def test_run_create_rejects_unknown_object(self):
        result = self.module._run_create("widget", {"x": "1"}, "pat-token")
        self.assertIn("Unknown object type", result)

    def test_run_create_requires_properties(self):
        result = self.module._run_create("contact", {}, "pat-token")
        self.assertIn("at least one property", result)

    def test_run_update_patches(self):
        with patch.object(self.module, "_api_request", return_value={"id": "12045"}) as mock:
            result = self.module._run_update("deal", "12045", {"dealstage": "closedwon"}, "pat-token")
        self.assertIn("Updated deal 12045", result)
        self.assertEqual(mock.call_args.args[0], "PATCH")
        self.assertEqual(mock.call_args.args[1], "/crm/v3/objects/deals/12045")

    def test_run_delete_archives(self):
        with patch.object(self.module, "_api_request", return_value={}) as mock:
            result = self.module._run_delete("contact", "501", "pat-token")
        self.assertIn("Archived contact 501", result)
        self.assertEqual(mock.call_args.args[0], "DELETE")
        self.assertEqual(mock.call_args.args[1], "/crm/v3/objects/contacts/501")

    def test_run_log_note_creates_and_associates(self):
        calls = []

        def fake(method, path, token, **kwargs):
            calls.append((method, path))
            return {"id": "77"} if path.endswith("/notes") else {}

        with patch.object(self.module, "_api_request", side_effect=fake):
            result = self.module._run_log_engagement("note", "deal", "12045", "Called client", "pat-token")
        self.assertIn("Logged note on deal 12045 (id: 77)", result)
        self.assertEqual(calls[0], ("POST", "/crm/v3/objects/notes"))
        self.assertEqual(
            calls[1],
            ("PUT", "/crm/v3/objects/notes/77/associations/default/deals/12045"),
        )

    def test_run_log_rejects_bad_kind(self):
        result = self.module._run_log_engagement("email", "deal", "1", "hi", "pat-token")
        self.assertIn("note", result)


class TestWriteExecute(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()
        self.api = MagicMock()
        self.api.get_secret.return_value = "pat-token"

    def test_create_without_token_is_blocked(self):
        self.api.get_secret.return_value = None
        tool = self.module.HubSpotCreateRecordTool(self.api)
        self.assertIn("not configured", tool.execute("contact email=a@b.com"))

    def test_create_execute_routes(self):
        tool = self.module.HubSpotCreateRecordTool(self.api)
        with patch.object(self.module, "_run_create", return_value="ok") as mock:
            result = tool.execute("contact email=a@b.com firstname=Jane")
        self.assertEqual(result, "ok")
        obj, props, token = mock.call_args.args
        self.assertEqual(obj, "contact")
        self.assertEqual(props["email"], "a@b.com")
        self.assertEqual(token, "pat-token")

    def test_delete_execute_handles_404(self):
        tool = self.module.HubSpotDeleteRecordTool(self.api)
        with patch.object(self.module, "_run_delete", side_effect=_http_error(404)):
            self.assertIn("404", tool.execute("contact 999"))

    def test_log_engagement_bad_usage(self):
        tool = self.module.HubSpotLogEngagementTool(self.api)
        self.assertIn("Usage", tool.execute("note deal"))


class TestSkill(unittest.TestCase):
    def test_skill_file_exists_with_frontmatter(self):
        skill_path = PLUGIN_DIR / "skills" / "hubspot_crm" / "SKILL.md"
        text = skill_path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"))
        self.assertIn("name: hubspot_crm", text)
        self.assertIn("display_name:", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
