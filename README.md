# Custom Voice Agent with Microsoft Foundry + Azure Voice Live (Python)

A minimal, up-to-date example of a **custom voice agent** using the current GA
Python SDK **`azure-ai-voicelive` (>= 1.2.0)**.

The published quickstart was written against an older **beta** of 1.2.0 and uses
the `AgentSessionConfig` / `agent_config=` pattern, which no longer works in GA.
This example uses the current, supported API.

## What changed (why the old docs fail)

| | Old beta docs | Current GA (this example) |
|---|---|---|
| Attach agent | `connect(..., agent_config=AgentSessionConfig(...))` | `connect(..., agent_name=..., project_name=...)` |
| Config style | typed `AgentSessionConfig` object | flattened `connect()` keyword arguments |
| API version | hardcoded `2026-01-01-preview` | left unset → SDK default (`2026-04-10` on GA 1.2.0) |
| Sync API | available | **removed** — SDK is async-only |

The old `FoundryAgentTool` classes were also removed. Agents are now selected at
connection time via `connect()` keywords and become the primary responder.

Source of truth: the official [`agent_v2_sample.py`](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/voicelive/azure-ai-voicelive/samples/agent_v2_sample.py)
in the Azure SDK for Python repo.

## Files

| File | Purpose |
|---|---|
| [create_agent.py](create_agent.py) | One-time: create/update a Foundry agent (model + instructions). |
| [voice_agent.py](voice_agent.py) | Connect to that agent and hold a live voice conversation. |
| [requirements.txt](requirements.txt) | Python dependencies. |
| [.env.example](.env.example) | Configuration template — copy to `.env`. |

## Prerequisites

- Python 3.10+
- A Microsoft Foundry resource + project, with a model deployed
- The `Foundry User` role assigned to your account (agent mode needs Entra ID)
- Audio for the microphone/speaker sample:
  - Windows: nothing extra — `pip install pyaudio` uses a prebuilt wheel
  - Linux: `sudo apt-get install -y portaudio19-dev libasound2-dev`
  - macOS: `brew install portaudio`

> Note: WSL2 has no audio devices by default. Run on native Windows (or a
> machine with a mic and speakers) for the voice conversation.

## Setup

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env     # then fill in the values

az login                   # agent mode requires Entra ID (no API keys)
```

**Linux / macOS:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # then fill in the values

az login                   # agent mode requires Entra ID (no API keys)
```

## Run

```bash
# 1. Create the agent (one time)
python create_agent.py

# 2. Talk to it
python voice_agent.py
```

Speak after you see `🎤 VOICE AGENT READY`. You can interrupt the agent by
talking over it (barge-in). Press `Ctrl+C` to quit.

## Notes

- **Auth:** Agent connections require Microsoft Entra ID. API-key auth is only
  for non-agent (raw model) Voice Live sessions.
- **Voice vs. behaviour:** The agent owns the instructions/behaviour; the voice,
  turn detection and audio settings are applied per session in
  `voice_agent.py` (`_setup_session`). You can instead store voice settings in
  the agent's metadata if you want the Foundry playground to reuse them.
- **`AGENT_PROJECT_NAME`** is the last path segment of your project endpoint.
- **Echo cancellation:** `_setup_session` enables server-side
  `input_audio_echo_cancellation` and `input_audio_noise_reduction`. Without
  these, on a laptop with open speakers the agent transcribes its own voice and
  interrupts itself. Headphones are still the most reliable fix.
- **Test without code first:** In the Foundry portal, open the agent's
  **Playground** and turn on **Voice mode** to talk to the agent in the browser.

## Troubleshooting

- **Agent connects and transcribes you, but never replies (no audio):** the
  agent's response is failing server-side. The most common cause is that the
  agent's model deployment does not exist in the project — e.g. the agent was
  created against a model name that was never deployed. `voice_agent.py` now
  logs the failure (look for `Agent response failed: ... agent_DeploymentNotFound`).
  Fix it by setting `MODEL_DEPLOYMENT_NAME` in `.env` to a model that is
  actually deployed in your project, then re-run `python create_agent.py`. The
  agent endpoint routes 100% of traffic to `@latest`, so the new version takes
  effect immediately.
- **The agent interrupts itself / hears its own voice:** enable echo
  cancellation (already done in `_setup_session`) or use headphones. You can
  also make barge-in less sensitive by raising the `ServerVad(threshold=...)`
  value in `_setup_session`.
