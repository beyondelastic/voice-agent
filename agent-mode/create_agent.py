#!/usr/bin/env python
"""
create_agent.py — Create (or update) a Foundry agent you can later talk to.

This is a ONE-TIME setup step. It uses the Azure AI Projects SDK to create a
"prompt agent": a model, the shared instructions, and the shared function tools.
Voice-specific settings (voice, turn detection) are applied at connection time in
voice_agent.py, so the agent stays reusable for both text and voice.

The instructions come from instructions.md and the tool schemas from tools.py
(both next to this script), so this example is self-contained.

Prerequisites:
  - `az login` (Entra ID auth)
  - PROJECT_ENDPOINT and MODEL_DEPLOYMENT_NAME set in your .env file

Run:
  python create_agent.py
"""

import os

from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionToolParam, PromptAgentDefinition

# Tools live alongside this script (tools.py, data.json).
from tools import TOOL_SCHEMAS

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))

# Persona lives in instructions.md next to this script.
with open(os.path.join(_HERE, "instructions.md"), encoding="utf-8") as _f:
    INSTRUCTIONS = _f.read().strip()


def main() -> None:
    endpoint = os.environ["PROJECT_ENDPOINT"]
    agent_name = os.environ.get("AGENT_NAME", "MyVoiceAgent")
    model = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

    # DefaultAzureCredential picks up your `az login` session automatically.
    project_client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())

    # Same tools as the native example, built as Foundry agent tool params.
    tools = [
        FunctionToolParam(name=s["name"], description=s["description"], parameters=s["parameters"])
        for s in TOOL_SCHEMAS
    ]

    # create_version() creates the agent if it doesn't exist, or adds a new
    # version if it does. Instructions + tools come from the shared package.
    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=model,
            instructions=INSTRUCTIONS,
            tools=tools,
        ),
    )

    print(f"Agent created/updated: {agent.name} (version {agent.version})")
    print(f"Tools: {', '.join(t['name'] for t in TOOL_SCHEMAS)}")
    print("You can now run: python voice_agent.py")


if __name__ == "__main__":
    main()
