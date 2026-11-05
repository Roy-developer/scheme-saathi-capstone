"""Try tool calls against the real permission code.

Run from the project folder:
    ..\\venv\\Scripts\\python.exe scripts\\try_permissions.py
"""

import asyncio
import sys
from pathlib import Path

# Lets Python find the "src" folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_servers.service_routing import SERVICE_TOOLS, ServiceClientRouter  # noqa: E402
from src.workflow.errors import MCPToolError  # noqa: E402


class FakeServer:
    """A pretend server. It only remembers whether it was called."""

    def __init__(self, name):
        self.name = name
        self.was_called = False

    async def call_tool(self, name, arguments):
        self.was_called = True
        return f"{self.name} ran {name}"


def try_call(role, tool, arguments, conversation="conv-42"):
    """Pretend an agent with `role` asks for `tool`, and print what happens.

    Example: try_call("documents", "check_documents", {})
        role         = "documents"         -> the badge the backend gives
        tool         = "check_documents"   -> the tool the LLM asks for
        arguments    = {}                  -> the extra details the LLM sends
        conversation = "conv-42"           -> the case the badge is for (default)
    """

    # ---- 1. Make the workers ------------------------------------------------
    # SERVICE_TOOLS has 4 names: rule-engine, schemes-kb, doc-check, mock-portal.
    # We make one FakeServer for each name and keep them in a dictionary:
    #   servers = {"rule-engine": FakeServer, "doc-check": FakeServer, ...}
    servers = {}
    for service_name in SERVICE_TOOLS:
        servers[service_name] = FakeServer(service_name)

    # ---- 2. Make the guard and give it a badge -------------------------------
    # This line does two things:
    #   a) ServiceClientRouter(clients=servers)
    #        builds a guard that knows where the 4 workers are.
    #   b) .for_actor(role, conversation)
    #        builds a NEW guard wearing the badge, e.g. role="documents",
    #        conversation="conv-42". (See service_routing.py, line 80.)
    # In the real app the backend does this, never the LLM.
    guard = ServiceClientRouter(clients=servers).for_actor(role, conversation)

    # ---- 3. Ask the guard to run the tool ------------------------------------
    print(f"{role} asks for {tool} {arguments}")
    try:
        # guard.call_tool(...) is the REAL permission code
        # (service_routing.py, lines 89-119). It checks in order:
        #   check 1: is the tool on this role's list?       (ACTOR_TOOLS)
        #   check 2: portal tools only: is the action allowed? (PORTAL_ACTIONS)
        #   check 3: portal tools only: same conversation as the badge?
        #   check 4: did the arguments try to set "actor"/"caller"?
        # Any failed check raises MCPToolError and jumps to "except" below.
        #
        # If all checks pass, the guard finds the owner of the tool and calls
        #   servers["doc-check"].call_tool(tool, arguments)
        # which is FakeServer.call_tool above. It returns "doc-check ran ...".
        #
        # call_tool is "async", so asyncio.run(...) is needed to run it
        # and wait for the answer.
        result = asyncio.run(guard.call_tool(tool, arguments))
        print(f"   ALLOWED: {result}")

    except MCPToolError as error:
        # We land here when the guard said no. The message tells you which
        # check failed, e.g. "This caller is not allowed to use this tool."
        print(f"   BLOCKED: {error}")

        # Prove that no worker did anything: every FakeServer still has
        # was_called == False. (The real tests check the same thing.)
        if not any(server.was_called for server in servers.values()):
            print("   (no server was called)")

    print()  # blank line between examples


# ---- Examples: change these or add your own, then run again ----

# Document agent checks documents. All checks pass.
# Expected:  ALLOWED: doc-check ran check_documents
try_call("documents", "check_documents", {})

# Document agent tries to submit a form. submit_draft is not on its list.
# Expected:  BLOCKED: This caller is not allowed to use this tool.      (check 1)
try_call("documents", "submit_draft", {"journey_id": "conv-42"})

# Application agent tries to approve. "approve" is not in its portal actions.
# Expected:  BLOCKED: This caller is not allowed to use this portal action.  (check 2)
try_call("application", "mock_portal", {"action": "approve", "journey_id": "conv-42"})

# Human approval approves. Only this role has "approve".
# Expected:  ALLOWED: mock-portal ran mock_portal
try_call("human_approval", "mock_portal", {"action": "approve", "journey_id": "conv-42"})

# Right role and action, but the badge says conv-42 and the request says conv-99.
# Expected:  BLOCKED: Portal calls require the bound journey context.   (check 3)
try_call("application", "submit_draft", {"journey_id": "conv-99"})

# Allowed tool, but the LLM tries to claim a role in the arguments.
# Expected:  BLOCKED: Tool arguments cannot set caller identity.        (check 4)
try_call("documents", "check_documents", {"actor": "human_approval"})
