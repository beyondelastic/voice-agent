#!/usr/bin/env python
"""
create_agent.py — Create (or update) a Foundry agent you can later talk to.

This is a ONE-TIME setup step. It uses the Azure AI Projects SDK to create a
simple "prompt agent": a model plus a system instruction. Voice-specific
settings (voice, turn detection, noise suppression) are NOT stored on the agent
here — they are applied at connection time in voice_agent.py. That keeps the
agent reusable for both text and voice.

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
from azure.ai.projects.models import PromptAgentDefinition

load_dotenv()


def main() -> None:
    endpoint = os.environ["PROJECT_ENDPOINT"]
    agent_name = os.environ.get("AGENT_NAME", "MyVoiceAgent")
    model = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4.1-mini")

    # DefaultAzureCredential picks up your `az login` session automatically.
    project_client = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())

    # create_version() creates the agent if it doesn't exist, or adds a new
    # version if it does. The instructions define the agent's behaviour.
    agent = project_client.agents.create_version(
        agent_name=agent_name,
        definition=PromptAgentDefinition(
            model=model,
            instructions=(
                "You are Tobi, a friendly voice assistant. "
                "Keep spoken answers short, clear and conversational."
            ),
        ),
    )

    print(f"Agent created/updated: {agent.name} (version {agent.version})")
    print("You can now run: python voice_agent.py")


if __name__ == "__main__":
    main()
