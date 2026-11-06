# Setup: Lead to CRM

Follow the steps in order. Fill everything in `values.json`, then run `apply`.

## 1. Create the credentials first

In n8n: **Credentials › Create**. After saving, copy the ID from the page URL (`/home/credentials/<ID>`) into `values.json`.

1. `slackApi` (used by 1 node(s): Notify)
   - `CRED_SLACKAPI_ID` = credential ID, `CRED_SLACKAPI_NAME` = its name

## 2. Fill in your own resources

- `HTTP_REQUEST_BASE_URL`: base URL of the API (keep it as is if it is a public API, change it for a client-hosted one) (used in 1 place(s): Push to CRM › url)
- `SLACK_CHANNELID_SALES_LEADS`: channelId (was: #sales-leads) (used in 1 place(s): Notify › channelId)

## 3. Secrets found in node parameters

These were pasted directly into nodes. Better: create a credential and point the node to it. If you keep them, put the value in `values.json`.

- `SECRET_HTTP_REQUEST_AUTHORIZATION` in Push to CRM › headerParameters.parameters.0

## 4. Build and import

```bash
python3 n8n_portable.py apply workflow.template.json values.json -o workflow.json
```

Then in n8n: **Workflows › Import from file › workflow.json**. Each node points to your credentials by ID, so you don't re-select them node by node.

## 5. Smoke test

- Run the workflow once with test data before activating it.
- Google OAuth: if your OAuth app is in *Testing* mode, refresh tokens expire after 7 days. Publish it (Audience › In production) or use Internal for Workspace.
