# HubSpot CRM

Search, read, and manage your HubSpot CRM directly from Row-Bot.

## What It Does

**Read (safe, no approval):**
- Search **contacts**, **companies**, **deals**, and **tickets**.
- Look up a single record by id.
- List deals and summarize the open pipeline by stage.

**Write (approval-gated — Row-Bot confirms before each action):**
- **Create** a contact, company, deal, or ticket.
- **Update** fields on a record.
- **Delete** (archive) a record.
- **Log** a note or task against a record.

## What It Does Not Do (Yet)

- No sending marketing/sales emails, sequence enrollment, or messaging contacts.
- No bulk operations, imports, or merges.
- No pipeline/stage label mapping (deal stages show HubSpot's internal values).
- Deletes are **archives** (HubSpot soft-delete), not permanent purges.

## Approval Model

The read tool (`hubspot_crm`) runs without approval. The four write tools are
declared **destructive**, so Row-Bot's approval gate applies:

- In **approve** mode, Row-Bot pauses and asks the user to confirm before the
  write runs.
- In **block** mode, the write tools are hidden from the agent entirely.

This means the agent can never create, change, or delete HubSpot data without
the user's explicit confirmation.

## Setup

You need a **HubSpot Private App** access token.

1. In HubSpot, go to **Settings → Integrations → Private Apps**.
2. **Create a private app**, name it (e.g. "Row-Bot").
3. On the **Scopes** tab, grant the scopes you need:
   - **Read (required):** `crm.objects.contacts.read`, `crm.objects.companies.read`,
     `crm.objects.deals.read`, `crm.objects.tickets.read`
   - **Write (required for create/update/delete/log):**
     `crm.objects.contacts.write`, `crm.objects.companies.write`,
     `crm.objects.deals.write`, `crm.objects.tickets.write`
   - Logging notes/tasks associates them to the target record, so grant the
     write scope for whichever object you attach them to.
4. Create the app and copy the **access token** (it starts with `pat-`).
5. In Row-Bot's Plugin Center, open HubSpot CRM, paste the token into
   **HubSpot Private App Token**, run **Test**, then enable the plugin.

The token is stored in Row-Bot's secret store (OS keyring). It is never written
to plugin files, logs, or the marketplace index.

## Configuration

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| HubSpot Private App Token | secret | — (required) | Private App access token with CRM scopes. |
| Default number of results | setting | `10` | Records returned per search or list, clamped to 1–30. |

## Permissions

| Permission | Why it is needed |
| --- | --- |
| `network` | Calls the HubSpot CRM API over HTTPS. |
| `account` | Reads and (with approval) writes your HubSpot account's CRM records. |

## Tools And Commands

Each tool accepts a single query string.

**`hubspot_crm`** (read):

| Command | Example |
| --- | --- |
| `search_contacts <query> [N]` | `search_contacts jane@acme.com` |
| `search_companies <query> [N]` | `search_companies Acme` |
| `search_deals <query> [N]` | `search_deals renewal 5` |
| `search_tickets <query> [N]` | `search_tickets login` |
| `list_deals [N]` | `list_deals 20` |
| `contact\|company\|deal\|ticket <id>` | `deal 12045` |

A bare query searches contacts.

**Write tools** (each asks for approval):

| Tool | Input | Example |
| --- | --- | --- |
| `hubspot_create_record` | `<object> key=value ...` | `contact email=jane@acme.com firstname=Jane` |
| `hubspot_update_record` | `<object> <id> key=value ...` | `deal 12045 dealstage=closedwon` |
| `hubspot_delete_record` | `<object> <id>` | `contact 501` |
| `hubspot_log_engagement` | `<note\|task> <object> <id> <text>` | `note deal 12045 Renewal confirmed` |

`<object>` is one of `contact`, `company`, `deal`, `ticket`. Quote values with
spaces, e.g. `dealname="Acme renewal"`.

## Network Behavior

The plugin makes live HTTPS requests to `api.hubapi.com` **only** when a tool is
run. It performs no network calls during install, validation, or registration.

## Tests

`tests/test_plugin.py` runs fully offline. All HubSpot API calls are mocked with
small synthetic responses (no real accounts, records, tokens, or network). The
tests cover manifest shape, command parsing, formatting, pipeline summary, the
read runners, all four write runners (create/update/delete/log), that write
tools are declared destructive while the read tool is not, and error handling
(missing token, HTTP 401/403/404/429).

Run them from the plugin directory:

```powershell
python -m pytest tests -q
```

## Manual / Live Checks (optional, not required by default validation)

Default validation is offline, so live behavior must be verified manually with a
**HubSpot test/developer account** (free — see below). Suggested smoke test:

1. **Read:** `search_contacts <a known contact>` returns the expected contact.
2. **Read:** `list_deals` returns deals and a pipeline summary.
3. **Create:** ask Row-Bot to create a test contact → approve the prompt →
   confirm it appears in HubSpot.
4. **Update:** update a field on that contact → approve → confirm the change.
5. **Log:** log a note on the contact → approve → confirm the note is attached.
6. **Delete:** delete the test contact → approve → confirm it is archived.
7. Removing the token makes **Test** fail clearly in Plugin Center.

Use a throwaway HubSpot developer/test account for live write checks so no real
customer data is affected.

## API And Limits

- Uses the HubSpot CRM v3 API (`/crm/v3/objects/...`): search, read, create
  (POST), update (PATCH), archive (DELETE), and default associations (PUT).
- HubSpot enforces per-app rate limits; on HTTP 429 the tools ask the user to
  retry shortly.
- Deal stages are returned as HubSpot's internal stage values; friendly stage
  labels depend on the account's pipeline configuration.

## License

Apache-2.0. See [LICENSE](LICENSE).
