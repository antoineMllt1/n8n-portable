---
name: n8n-portable
description: Turn an exported n8n workflow into a reusable, client-ready template and fill it back in for a new client. Use when the user wants to hand over, resell, duplicate or move an n8n workflow to another client or instance, asks how to avoid re-selecting credentials node by node after import, or wants to strip their own sheet IDs, channel IDs, emails, pinned data and hardcoded API keys out of a workflow JSON before sharing it.
---

# n8n-portable

Makes an n8n workflow portable between clients. One command replaces every client-specific value with a named placeholder, another fills them back in from a single `values.json`, and the result imports with every node already pointing to the new client's credentials.

Script: `scripts/n8n_portable.py` (Python 3.8+, standard library only, works offline).

## When to use

- "I need to give this workflow to a client / deploy it on their instance."
- "After import I have to re-pick the credential in 12 nodes."
- "Remove my IDs / keys from this workflow before I share it."
- "Make a template of this workflow I can sell or reuse."

## Steps

1. Get the workflow JSON. In n8n: **⋯ › Download**, or the user gives a path. Several workflows: run the steps on each file.
2. Scan first and show the user what was found:
   ```bash
   python3 scripts/n8n_portable.py scan <workflow.json>
   ```
   It lists the credentials to create (type + nodes using them), client-specific values (resource locators like Google Sheet / Slack channel / Notion DB IDs, recipient emails, HTTP base URLs), hardcoded secrets, and community node packages.
3. Review the list with the user. If a hardcoded secret is found, recommend moving it to an n8n credential before handover (say which node). If a value is not client-specific (a public API base URL), say it can keep its original value.
4. Build the handover kit:
   ```bash
   python3 scripts/n8n_portable.py templatize <workflow.json> -o handover/<client-or-workflow>
   ```
   Output: `workflow.template.json` (placeholders like `__N8NP_GOOGLE_SHEETS_DOCUMENTID_LEADS__`, pinned data removed, set to inactive, instance ID removed), `values.json` (one empty slot per value, with a hint), `SETUP.md` (credential creation order, values to fill, import and smoke test), and `originals.local.json` (the user's own original values).
5. Warn clearly: **`originals.local.json` stays with the user. Never send it to the client**: it contains their own IDs and any secrets found.
6. To deploy for a client, fill `values.json` (credential IDs come from the credential page URL `/home/credentials/<ID>`), then:
   ```bash
   python3 scripts/n8n_portable.py apply handover/<x>/workflow.template.json handover/<x>/values.json -o workflow.<client>.json
   ```
   `apply` refuses to write if a value is missing and lists the missing keys. It gives each webhook a fresh `webhookId` so two copies on one instance do not clash.
7. Remind the user to run the workflow once with test data before activating it.

## Rules

- Never print secret values in full. The scan masks them; keep it that way in your answer.
- Do not edit the user's original export; write to a new folder.
- Expressions (values starting with `=`) are left untouched: they are logic, not client data.
- If something looks client-specific but was not templated (for example an ID inside a Code node), point it out instead of guessing. The script does not parse JavaScript.
