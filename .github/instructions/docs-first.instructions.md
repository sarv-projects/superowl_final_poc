---
applyTo: "**/*.{py,js,ts,tsx,jsx,md,toml,yml,yaml,json}"
---

For any change involving third-party libraries, frameworks, SDKs, external APIs, or platform services:
- Retrieve current documentation before implementation.
- Prefer Docfork MCP tools first: search_docs, then fetch_doc.
- If docs retrieval fails, use another trusted available docs source before making assumptions.
- Use exact documented parameter names, payload fields, and endpoint semantics.
- For version-dependent behavior, verify and state the version context.
