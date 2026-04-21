# Copilot Workspace Instructions

## Documentation-First Policy
- For any task involving third-party libraries, frameworks, SDKs, APIs, CLIs, or cloud services, use documentation tools first.
- This applies to all ecosystems, including (but not limited to): VAPI, LangChain, LangGraph, CrewAI, FastAPI, OpenAI SDKs, Slack APIs, Nango, httpx, Pydantic, and database/ORM frameworks.
- Preferred flow:
  1. Use Docfork MCP (`search_docs`) with a targeted query.
  2. Use Docfork MCP (`fetch_doc`) on the most relevant official page.
  3. Base implementation and code suggestions on retrieved documentation.
- Do not rely on model memory for version-sensitive behavior when docs are available.
- If Docfork cannot provide sufficient results, use another available docs source before guessing.

## Automatic Third-Party Rule
- Default behavior: whenever a request touches any external library/framework/API, fetch current docs first, then implement.
- If the user request is purely language built-ins or project-local logic, docs lookup is optional.

## Accuracy Rules
- Prefer exact field names, payload shapes, and endpoint usage from docs.
- If uncertain after retrieval, state uncertainty and request one extra doc lookup rather than guessing.
- Include short citations by naming the doc page title/URL used for critical behavior.
- For setup or migration tasks, verify version-specific docs and call out version assumptions explicitly.

## Practical Output Rules
- Keep code changes minimal and compatible with current project style.
- Avoid speculative refactors unrelated to the user request.
