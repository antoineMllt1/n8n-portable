# n8n-portable

A Claude skill (and a standalone Python script) that makes an n8n workflow portable between clients.

It turns an exported workflow into a template where every client-specific value is a named placeholder, writes a setup checklist, then fills the template back in from one `values.json` file. The result imports with every node already pointing to the new client's credentials.

## Why

The workflow JSON transfers cleanly. The pain starts after import: re-picking the credential in every node, hunting down the Google Sheet ID, Slack channel and recipient email you hardcoded, and hoping you didn't leave your own API key or pinned test data in there.

This came up again in October 2026 on the n8n forum ([*What is your trick for handing over n8n workflows without the credentials setup pain?*](https://community.n8n.io/t/what-is-your-trick-for-handing-over-n8n-workflows-without-the-credentials-setup-pain/323533), 13 replies). The answers are all manual: sticky notes listing the credentials, a "Config" Set node, a Loom video. Handover-doc generators exist, but they document the workflow without making it re-importable.

## What it does

| Command | Does |
|---|---|
| `scan` | Lists the credentials to create (type + nodes), client-specific values, hardcoded secrets and community nodes |
| `templatize` | Writes `workflow.template.json`, `values.json`, `SETUP.md` and `originals.local.json` |
| `apply` | Fills the template from `values.json`, refuses if anything is missing, gives webhooks fresh IDs |

What gets templated:

- **Resource locators**: Google Sheets document and tab, Slack channel, Notion database, Airtable base and table, Drive folder and file, and so on. The same ID used in 5 nodes becomes **one** placeholder.
- **Recipient values**: `toEmail`, `fromEmail`, `sendTo`, `chatId`, `channelId`, `calendarId`, …
- **HTTP Request base URLs**.
- **Credential references**: the ID and name in every node.
- **Hardcoded secrets** (OpenAI / Slack / GitHub / Google keys, Bearer tokens, JWTs, `Authorization` / `x-api-key` headers). They are flagged so you can move them into a credential.

The template is also cleaned up: pinned data is removed (it often holds real customer data), the instance ID and version metadata are stripped, and the workflow is set to inactive. Expressions (`={{ ... }}`) are left alone.

## Install

As a Claude Code skill:

```bash
git clone https://github.com/antoineMllt1/n8n-portable ~/.claude/skills/n8n-portable
```

Then ask Claude something like *"make this workflow ready to hand over to a client: ./exports/lead-router.json"*.

Standalone (Python 3.8+, no dependencies):

```bash
python3 scripts/n8n_portable.py --help
```

## Example

Tested on a real public workflow: [*Contact Form Text Classifier for eCommerce*](https://github.com/Zie619/n8n-workflows) (14 nodes, 5 Google Sheets nodes, 5 email nodes).

```text
$ python3 scripts/n8n_portable.py scan contact-form-classifier.json
Workflow: Contact Form Text Classifier for eCommerce  (14 nodes)

Credentials to create (3):
  - openAiApi  used by 1 node(s): OpenAI
  - smtp  used by 5 node(s): Prod. Dep., Quote Dep., Gen. Dep., Order Dep., Other Dep.
  - googleSheetsOAuth2Api  used by 5 node(s): Quote DB, Prod DB, General DB, Order DB, Other DB

Client-specific values (4):
  - EMAIL_SEND_TOEMAIL: toEmail  ×5
  - EMAIL_SEND_FROMEMAIL: fromEmail  ×5
  - GOOGLE_SHEETS_SHEETNAME_FOGLIO1: sheetName (was: Foglio1) — format gid=<number>  ×5
  - GOOGLE_SHEETS_DOCUMENTID_CLASSIFIED_CONTACT_FORM: documentId (was: Classified Contact Form)  ×5

Hardcoded secrets (0):

$ python3 scripts/n8n_portable.py templatize contact-form-classifier.json -o handover/acme
Wrote handover/acme/workflow.template.json, values.json, SETUP.md, originals.local.json
3 credential slot(s), 4 client value(s), 0 secret(s) → 10 placeholders
Do NOT send originals.local.json to the client: it holds your own IDs and secrets.

$ python3 scripts/n8n_portable.py apply handover/acme/workflow.template.json handover/acme/values.json -o workflow.acme.json
Wrote workflow.acme.json: 10 placeholder(s) filled, 14 nodes. Import it in n8n.
```

That's 42 hand edits across 11 nodes (credential ID and name, sheet, tab, recipients) turned into 10 lines in one file.

The full output for a smaller workflow (webhook → HTTP Request with a hardcoded Bearer token → Slack) is in [`examples/lead-to-crm-handover/`](examples/lead-to-crm-handover).

## Limits

- It does not read JavaScript in Code nodes. An ID hardcoded in a Code node stays there (Claude points these out when using the skill).
- Credential *secrets* never leave n8n. The client still creates each credential once, and `SETUP.md` gives them the order.
- Only the parameter names listed in the script are treated as client data. Open an issue if your node uses another one.
- `originals.local.json` holds **your** original values. It is git-ignored: don't send it.

## License

MIT, © 2026 Antoine Millot
