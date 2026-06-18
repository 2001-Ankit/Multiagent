# Multi-agent workflow

## Gmail delivery tool

The delivery agent exposes a Gmail API based email tool at
`src.delivery_agent.tools.send_email`.

Setup:

1. Enable the Gmail API in a Google Cloud project.
2. Configure the OAuth consent screen.
3. Create an OAuth client ID with application type `Desktop app`.
4. Download the OAuth client JSON as `credentials.json` in the project root.
5. Install dependencies with `uv sync`.
6. Run the email tool once from a local terminal so the OAuth browser flow can
   create `token.json`.

Both `credentials.json` and `token.json` are ignored by git. You can override
their locations with:

```env
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
```

To use it as a LangChain tool, import and bind it to an agent:

```python
from langchain_openai import ChatOpenAI

from src.delivery_agent.tools import send_email

llm = ChatOpenAI(...)
delivery_llm = llm.bind_tools([send_email])
```

## Gmail MCP server

The same Gmail send capability is also available as an MCP server:

```powershell
uv run python -m src.delivery_agent.mcp_server
```

Register that command in any MCP-compatible host. The exposed MCP tool is named
`send_email` and accepts `to`, `subject`, `body`, `cc`, and `bcc`.
