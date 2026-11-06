#!/usr/bin/env python3
"""n8n-portable: turn an exported n8n workflow into a reusable template for another client, then fill it back in.

  scan        <workflow.json>                     list credentials, client-specific values and hardcoded secrets
  templatize  <workflow.json> -o <dir>            write workflow.template.json + values.json + SETUP.md (+ originals.local.json)
  apply       <workflow.template.json> <values.json> -o <out.json>   fill the placeholders, ready to import

Standard library only. Nothing is sent anywhere.
"""
import argparse, copy, json, re, sys, uuid
from pathlib import Path

TOKEN = "__N8NP_{}__"
TOKEN_RE = re.compile(r"__N8NP_[A-Z0-9_]+__")

# Resource-locator params that are not client data (model pickers etc.)
SKIP_RL = {"model", "modelId", "modelName"}
# Plain string params that usually hold client-specific values
CLIENT_KEYS = {
    "toEmail": "email", "fromEmail": "email", "sendTo": "email", "to": "email", "cc": "email", "bcc": "email",
    "replyTo": "email", "chatId": "id", "channel": "id", "channelId": "id", "spreadsheetId": "id",
    "databaseId": "id", "baseId": "id", "tableId": "id", "folderId": "id", "fileId": "id", "pageId": "id",
    "listId": "id", "boardId": "id", "calendarId": "id", "workspaceId": "id", "projectId": "id",
}
SECRET_RES = [
    re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"xox[abposr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
]
SECRET_PARAM_NAMES = re.compile(r"(?i)^(authorization|x-api-key|api[_-]?key|apikey|token|access[_-]?token|secret|password)$")


def slug(s):
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(s)).strip("_").upper()
    return s[:40] or "VALUE"


def service_of(node_type):
    base = node_type.split(".")[-1]
    base = re.sub(r"(Trigger|Tool)$", "", base)
    return slug(re.sub(r"(?<!^)(?=[A-Z])", "_", base))


def is_expression(v):
    return isinstance(v, str) and v.startswith("=")


def mask(v):
    v = str(v)
    return v[:4] + "…" + f"({len(v)} chars)" if len(v) > 8 else "…"


class Collector:
    def __init__(self):
        self.values = {}   # key -> {kind, original, hint, where[]}
        self.by_orig = {}  # (kind, original) -> key
        self.creds = {}    # type -> {names:set, nodes:[]}

    def add(self, kind, original, label, hint, where, secret=False):
        k = (kind, original)
        if k in self.by_orig:
            key = self.by_orig[k]
        else:
            key = label
            i = 2
            while key in self.values:
                key = f"{label}_{i}"; i += 1
            self.by_orig[k] = key
            self.values[key] = {"kind": kind, "original": original, "hint": hint, "secret": secret, "where": []}
        self.values[key]["where"].append(where)
        return TOKEN.format(key)


def find_secret(s):
    return any(r.search(s) for r in SECRET_RES)


def walk(obj, node, path, col):
    """Return a copy of obj with client values replaced by tokens."""
    svc = service_of(node.get("type", ""))
    where = f"{node.get('name')} › {'.'.join(path)}"
    if isinstance(obj, dict):
        if obj.get("__rl") is True:
            key = path[-1] if path else ""
            val = obj.get("value")
            if key in SKIP_RL or not isinstance(val, str) or not val or is_expression(val) or TOKEN_RE.search(val):
                return copy.deepcopy(obj)
            hint = obj.get("cachedResultName") or ""
            label = f"{svc}_{slug(key)}" + (f"_{slug(hint)}" if hint else "")
            fmt = " — format gid=<number>" if val.startswith("gid=") else (" — paste the full URL" if obj.get("mode") == "url" else "")
            tok = col.add(f"rl:{key}", val, label, (f"{key} (was: {hint})" if hint else key) + fmt, where)
            out = {k: v for k, v in obj.items() if k not in ("cachedResultName", "cachedResultUrl")}
            out["value"] = tok
            return out
        # header / query parameter pairs: {name: "Authorization", value: "Bearer ..."}
        if "name" in obj and "value" in obj and isinstance(obj.get("value"), str) \
                and SECRET_PARAM_NAMES.match(str(obj["name"])) and obj["value"] and not is_expression(obj["value"]):
            out = dict(obj)
            out["value"] = col.add("secret", obj["value"], f"SECRET_{svc}_{slug(obj['name'])}",
                                   f"{obj['name']} (move this to an n8n credential)", where, secret=True)
            return out
        return {k: walk(v, node, path + [k], col) for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk(v, node, path + [str(i)], col) for i, v in enumerate(obj)]
    if isinstance(obj, str) and obj and not TOKEN_RE.search(obj):
        key = path[-1] if path else ""
        if find_secret(obj):
            return col.add("secret", obj, f"SECRET_{svc}_{slug(key)}", f"{key} (hardcoded secret, move it to a credential)",
                           where, secret=True) if not is_expression(obj) else obj
        if key in CLIENT_KEYS and not is_expression(obj):
            return col.add(f"str:{key}", obj, f"{svc}_{slug(key)}", key, where)
        if key == "url" and not is_expression(obj) and node.get("type", "").endswith("httpRequest"):
            m = re.match(r"^(https?://[^/]+)(.*)$", obj)
            if m:
                tok = col.add("url", m.group(1), f"{svc}_BASE_URL", "base URL of the API (keep it as is if it is a public API, change it for a client-hosted one)", where)
                return tok + m.group(2)
    return obj


def templatize_workflow(wf):
    col = Collector()
    out = copy.deepcopy(wf)
    for meta_key in ("id", "versionId", "shared", "homeProject", "createdAt", "updatedAt"):
        out.pop(meta_key, None)
    if isinstance(out.get("meta"), dict):
        out["meta"].pop("instanceId", None)
    out["pinData"] = {}
    out["active"] = False
    community = set()
    new_nodes = []
    for node in out.get("nodes", []):
        t = node.get("type", "")
        if t and not (t.startswith("n8n-nodes-base.") or t.startswith("@n8n/")):
            community.add(t.split(".")[0])
        n = dict(node)
        if node.get("type") != "n8n-nodes-base.stickyNote":
            n["parameters"] = walk(node.get("parameters", {}), node, [], col)
        creds = node.get("credentials") or {}
        new_creds = {}
        for ctype, ref in creds.items():
            c = col.creds.setdefault(ctype, {"names": set(), "nodes": []})
            c["names"].add((ref or {}).get("name", ""))
            c["nodes"].append(node.get("name"))
            new_creds[ctype] = {"id": TOKEN.format("CRED_" + slug(ctype) + "_ID"), "name": TOKEN.format("CRED_" + slug(ctype) + "_NAME")}
        if creds:
            n["credentials"] = new_creds
        if "webhookId" in n:
            n["webhookId"] = "__N8NP_WEBHOOK_ID__"
        new_nodes.append(n)
    out["nodes"] = new_nodes
    return out, col, sorted(community)


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def cmd_scan(a):
    wf = load(a.workflow)
    _, col, community = templatize_workflow(wf)
    print(f"Workflow: {wf.get('name', '?')}  ({len(wf.get('nodes', []))} nodes)\n")
    print(f"Credentials to create ({len(col.creds)}):")
    for ctype, c in col.creds.items():
        print(f"  - {ctype}  used by {len(c['nodes'])} node(s): {', '.join(c['nodes'])}")
    plain = {k: v for k, v in col.values.items() if not v["secret"]}
    secrets = {k: v for k, v in col.values.items() if v["secret"]}
    print(f"\nClient-specific values ({len(plain)}):")
    for k, v in plain.items():
        print(f"  - {k}: {v['hint']}  ×{len(v['where'])}")
    print(f"\nHardcoded secrets ({len(secrets)}):")
    for k, v in secrets.items():
        print(f"  - {k}: {mask(v['original'])} in {v['where'][0]}")
    if community:
        print(f"\nCommunity node packages the client must install: {', '.join(community)}")


def setup_md(wf, col, community):
    lines = [f"# Setup: {wf.get('name', 'workflow')}", "",
             "Follow the steps in order. Fill everything in `values.json`, then run `apply`.", ""]
    lines += ["## 1. Create the credentials first", "",
              "In n8n: **Credentials › Create**. After saving, copy the ID from the page URL (`/home/credentials/<ID>`) into `values.json`.", ""]
    for i, (ctype, c) in enumerate(col.creds.items(), 1):
        lines.append(f"{i}. `{ctype}` (used by {len(c['nodes'])} node(s): {', '.join(c['nodes'])})")
        lines.append(f"   - `CRED_{slug(ctype)}_ID` = credential ID, `CRED_{slug(ctype)}_NAME` = its name")
    plain = [(k, v) for k, v in col.values.items() if not v["secret"]]
    if plain:
        lines += ["", "## 2. Fill in your own resources", ""]
        for k, v in plain:
            lines.append(f"- `{k}`: {v['hint']} (used in {len(v['where'])} place(s): {'; '.join(v['where'][:3])}{'…' if len(v['where']) > 3 else ''})")
    secrets = [(k, v) for k, v in col.values.items() if v["secret"]]
    if secrets:
        lines += ["", "## 3. Secrets found in node parameters", "",
                  "These were pasted directly into nodes. Better: create a credential and point the node to it. If you keep them, put the value in `values.json`.", ""]
        for k, v in secrets:
            lines.append(f"- `{k}` in {v['where'][0]}")
    if community:
        lines += ["", "## Community nodes to install first", ""] + [f"- `{c}` (Settings › Community nodes)" for c in community]
    n = 4 if secrets else 3
    lines += ["", f"## {n}. Build and import", "", "```bash",
              "python3 n8n_portable.py apply workflow.template.json values.json -o workflow.json", "```", "",
              "Then in n8n: **Workflows › Import from file › workflow.json**. Each node points to your credentials by ID, so you don't re-select them node by node.", "",
              f"## {n+1}. Smoke test", "", "- Run the workflow once with test data before activating it.",
              "- Google OAuth: if your OAuth app is in *Testing* mode, refresh tokens expire after 7 days. Publish it (Audience › In production) or use Internal for Workspace."]
    return "\n".join(lines) + "\n"


def cmd_templatize(a):
    wf = load(a.workflow)
    tpl, col, community = templatize_workflow(wf)
    d = Path(a.out); d.mkdir(parents=True, exist_ok=True)
    (d / "workflow.template.json").write_text(json.dumps(tpl, indent=2, ensure_ascii=False), encoding="utf-8")
    values = {}
    for ctype in col.creds:
        values[f"CRED_{slug(ctype)}_ID"] = {"value": "", "hint": f"ID of your {ctype} credential"}
        values[f"CRED_{slug(ctype)}_NAME"] = {"value": "", "hint": f"name of your {ctype} credential"}
    for k, v in col.values.items():
        values[k] = {"value": "", "hint": v["hint"], "used_in": len(v["where"])}
    (d / "values.json").write_text(json.dumps(values, indent=2, ensure_ascii=False), encoding="utf-8")
    originals = {k: v["original"] for k, v in col.values.items()}
    for ctype, c in col.creds.items():
        originals[f"CRED_{slug(ctype)}_NAME"] = sorted(c["names"])[0] if c["names"] else ""
    (d / "originals.local.json").write_text(json.dumps(originals, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / "SETUP.md").write_text(setup_md(wf, col, community), encoding="utf-8")
    n_tok = len(set(TOKEN_RE.findall(json.dumps(tpl)))) - (1 if "__N8NP_WEBHOOK_ID__" in json.dumps(tpl) else 0)
    print(f"Wrote {d}/workflow.template.json, values.json, SETUP.md, originals.local.json")
    print(f"{len(col.creds)} credential slot(s), {len([v for v in col.values.values() if not v['secret']])} client value(s), "
          f"{len([v for v in col.values.values() if v['secret']])} secret(s) → {n_tok} placeholders")
    print("Do NOT send originals.local.json to the client: it holds your own IDs and secrets.")


def cmd_apply(a):
    tpl_text = Path(a.template).read_text(encoding="utf-8")
    values = load(a.values)
    flat = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in values.items()}
    needed = sorted(set(TOKEN_RE.findall(tpl_text)) - {"__N8NP_WEBHOOK_ID__"})
    missing = [t[7:-2] for t in needed if not flat.get(t[7:-2])]
    if missing:
        print("Missing values in " + a.values + ":\n  - " + "\n  - ".join(missing), file=sys.stderr)
        sys.exit(1)
    wf = json.loads(tpl_text)

    def fill(o):
        if isinstance(o, dict):
            return {k: fill(v) for k, v in o.items()}
        if isinstance(o, list):
            return [fill(v) for v in o]
        if isinstance(o, str) and "__N8NP_" in o:
            if o == "__N8NP_WEBHOOK_ID__":
                return str(uuid.uuid4())
            return TOKEN_RE.sub(lambda m: str(flat[m.group(0)[7:-2]]), o)
        return o

    out = fill(wf)
    left = TOKEN_RE.findall(json.dumps(out))
    if left:
        print(f"Unfilled placeholders: {sorted(set(left))}", file=sys.stderr); sys.exit(1)
    Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {a.out}: {len(needed)} placeholder(s) filled, {len(out.get('nodes', []))} nodes. Import it in n8n.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    s1 = s.add_parser("scan"); s1.add_argument("workflow"); s1.set_defaults(f=cmd_scan)
    s2 = s.add_parser("templatize"); s2.add_argument("workflow"); s2.add_argument("-o", "--out", default="handover"); s2.set_defaults(f=cmd_templatize)
    s3 = s.add_parser("apply"); s3.add_argument("template"); s3.add_argument("values"); s3.add_argument("-o", "--out", default="workflow.json"); s3.set_defaults(f=cmd_apply)
    a = p.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
