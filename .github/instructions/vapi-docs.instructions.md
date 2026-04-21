---
applyTo: "app/**/*.py,vapi_migrate.py,tests/**/*.py"
---

When the task involves VAPI behavior, payloads, endpoints, assistant overrides, tools, or webhook events:
- Use Docfork MCP tools (`search_docs`, then `fetch_doc`) before coding.
- Prefer current official docs over assumptions.
- Verify required fields and nesting in request payloads.
- If project code differs from docs, call out the mismatch and propose documented fixes.
