# Native Voice Agent — gpt-realtime (speech-to-speech)

Talk to a **native audio model** (`gpt-realtime`) with Azure Voice Live. One
model hears your audio and speaks its reply directly — lowest latency, most
natural voice, no separate speech-to-text / text-to-speech step.

This is the counterpart to [`../agent-mode`](../agent-mode). Same audio plumbing,
different connection:

| | Native (this folder) | Agent mode ([../agent-mode](../agent-mode)) |
|---|---|---|
| Connect | `connect(..., model="gpt-realtime")` | `connect(..., agent_name=..., project_name=...)` |
| Speech | Model generates audio itself | Cascaded: Azure STT → text model → Azure TTS |
| Reasoning model | `gpt-realtime` | your Foundry agent's model (e.g. gpt-5-mini) |
| Instructions | in code (`instructions=`) | on the Foundry agent |
| Tools | in code (`tools=[...]`) | configured on the agent |
| Managed by Foundry Agent Service | ❌ | ✅ (versioning, knowledge, eval, monitor) |

**When to use native:** latency and voice naturalness matter most, and your
logic fits in the app. **When to use agent mode:** you want centrally-managed,
versioned, observable behaviour with built-in knowledge/tools.

> You do **not** deploy `gpt-realtime` — Voice Live is fully managed and
> provisions the audio model automatically.

## Files

| File | Purpose |
|---|---|
| [voice_realtime.py](voice_realtime.py) | Connect to `gpt-realtime` and hold a live voice conversation. |
| [requirements.txt](requirements.txt) | Python dependencies. |
| [.env.example](.env.example) | Configuration template — copy to `.env`. |

## Prerequisites

- Python 3.10+
- A Microsoft Foundry / Azure AI Services resource (Voice Live endpoint)
- Audio for the microphone/speaker sample:
  - Windows: nothing extra — `pip install pyaudio` uses a prebuilt wheel
  - Linux: `sudo apt-get install -y portaudio19-dev libasound2-dev`
  - macOS: `brew install portaudio`

> WSL2 has no audio devices by default — run on native Windows (or any machine
> with a mic and speakers).

## Setup

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env     # then fill in AZURE_VOICELIVE_ENDPOINT

az login                   # or set AZURE_VOICELIVE_API_KEY in .env
```

**Linux / macOS:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # then fill in AZURE_VOICELIVE_ENDPOINT

az login                   # or set AZURE_VOICELIVE_API_KEY in .env
```

## Run

```bash
python voice_realtime.py
```

Speak after you see `🎤 REALTIME VOICE READY`. Interrupt the model by talking
over it (barge-in). Press `Ctrl+C` to quit.

## The demo assistant: "Clara" (VitalCare Health Insurance)

The example ships as a health-insurance member-support assistant with **function
calling**. The persona, tools and data are **shared** with the Foundry-agent
example — see [`../shared`](../shared). The model calls these tools (mock data —
no real member data/PHI):

| Tool | What it does | Try saying |
|---|---|---|
| `get_claim_status` | Status/details of a claim | "What's the status of claim CLM-1002?" |
| `check_benefit_coverage` | Is a service covered + copay | "Is urgent care covered?" |
| `find_in_network_provider` | In-network providers by specialty | "Find a cardiologist near 90210." |
| `get_deductible_status` | Deductible / out-of-pocket left | "How much of my deductible is left? Member M-9087." |

## Customize

- **Behaviour:** edit [instructions.md](instructions.md). (Or override per-run
  via `INSTRUCTIONS` in `.env`.)
- **Tools:** edit [tools.py](tools.py). In a real system the tool functions
  would call your claims/eligibility/provider APIs.
- **Data:** edit the shared [`../data/data.json`](../data/data.json).
- **Voice:** set `VOICE_NAME` (alloy, echo, fable, onyx, nova, shimmer, marin, cedar).


