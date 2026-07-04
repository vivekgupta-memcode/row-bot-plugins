---
name: hubspot_crm
display_name: HubSpot CRM
icon: contacts
description: Guides the agent on when and how to use the HubSpot CRM tool to look up contacts, companies, deals, and support tickets, and to summarize the sales pipeline.
tags:
  - crm
  - sales
  - hubspot
version: "0.1"
author: GokulAIx
---

# HubSpot CRM

You have access to several HubSpot CRM tools. **Reading** is safe and instant.
**Writing** (create/update/delete/log) changes the user's live CRM, so those
tools are approval-gated — Row-Bot will ask the user to confirm before they run.

Tools:

- `hubspot_crm` — read: search, list, and detail (no approval needed).
- `hubspot_create_record` — create a record (approval-gated).
- `hubspot_update_record` — update fields on a record (approval-gated).
- `hubspot_delete_record` — archive/delete a record (approval-gated).
- `hubspot_log_engagement` — log a note or task on a record (approval-gated).

## When To Use

- The user asks about a customer, lead, contact, or the company behind a deal.
- The user asks about sales: open deals, pipeline value, deal stage, or what is
  closing soon.
- The user asks about a support ticket or a customer's ticket history.
- The user references HubSpot, "the CRM", "our pipeline", or a named account.
- The user wants a quick summary of pipeline health by stage.
- The user asks to add, change, remove, or note something on a CRM record — use
  the matching write tool and expect an approval prompt.

Do not use these tools for sending email or scheduling — Row-Bot has separate
Gmail and Calendar tools for that.

## Read commands (`hubspot_crm`)

| Command | Example | Purpose |
| --- | --- | --- |
| `search_contacts <query> [N]` | `search_contacts jane@acme.com` | Find contacts by name, email, or company. |
| `search_companies <query> [N]` | `search_companies Acme` | Find companies. |
| `search_deals <query> [N]` | `search_deals renewal` | Find deals by name. |
| `search_tickets <query> [N]` | `search_tickets login issue` | Find support tickets. |
| `list_deals [N]` | `list_deals 20` | List deals and summarize the pipeline by stage. |
| `contact <id>` | `contact 501` | Full detail for one contact. |
| `company <id>` | `company 88` | Full detail for one company. |
| `deal <id>` | `deal 12045` | Full detail for one deal. |
| `ticket <id>` | `ticket 990` | Full detail for one ticket. |

A bare query without a command searches contacts.

## Write tools (approval-gated)

| Tool | Input | Example |
| --- | --- | --- |
| `hubspot_create_record` | `<object> key=value ...` | `contact email=jane@acme.com firstname=Jane` |
| `hubspot_update_record` | `<object> <id> key=value ...` | `deal 12045 dealstage=closedwon amount=20000` |
| `hubspot_delete_record` | `<object> <id>` | `contact 501` |
| `hubspot_log_engagement` | `<note|task> <object> <id> <text>` | `note deal 12045 Renewal confirmed on call` |

`<object>` is one of `contact`, `company`, `deal`, `ticket`. Quote values with
spaces: `dealname="Acme renewal"`.

## Write safety

- Before a write, confirm the target and values with the user in plain language,
  then call the tool — Row-Bot will still show its own approval prompt.
- Prefer reading first (search to find the right id) before updating or deleting.
- Never guess record ids; look them up. Never delete unless the user clearly
  asked to remove that specific record.

## Presentation Tips

- Summarize the most relevant few records instead of dumping every field.
- When answering pipeline questions, lead with the `list_deals` pipeline summary
  (counts and totals by stage), then highlight notable deals.
- Deal stages are shown as HubSpot's internal stage values; if the user needs a
  friendly stage name, explain that stage labels depend on their pipeline setup.
- Look up a single record by id only when the user wants full detail.
- Never expose the access token or invent records; if the tool reports missing
  setup or an auth error, tell the user to check the token in Plugin Center.
