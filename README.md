# Custom Voice Agents with Microsoft Foundry + Azure Voice Live (Python)

Two minimal, up-to-date examples of building a **voice agent** with the current
GA Python SDK **`azure-ai-voicelive` (>= 1.2.0)** — showing the two ways Voice
Live can drive a conversation.

The published quickstart was written against an older **beta** and uses the
`AgentSessionConfig` / `agent_config=` pattern, which no longer works in GA.
These examples use the current, supported `connect()` API.

## The two options

| | [agent-mode/](agent-mode) | [native-realtime/](native-realtime) |
|---|---|---|
| What | Custom **Foundry agent** | Native **gpt-realtime** model |
| Connect | `connect(agent_name=..., project_name=...)` | `connect(model="gpt-realtime")` |
| Speech pipeline | Cascaded: Azure STT → text model → Azure TTS | Native speech-to-speech (one model) |
| Reasoning model | your agent's model (e.g. gpt-5-mini) | gpt-realtime |
| Instructions & tools | managed on the Foundry agent | defined in code |
| Extras | versioning, knowledge, tools, eval, monitor | lowest latency, most natural voice |
| Best when | governed, reusable, observable assistant | latency & voice quality matter most |

Both are valid for a "custom voice agent" — they differ in **where** the
customization lives (a managed agent vs. your code) and the **speech
architecture**. See each folder's README for details and setup.

> Voice Live is fully managed: you do **not** deploy the speech models
> (STT/TTS or `gpt-realtime`). In agent mode you *do* deploy the agent's text
> reasoning model in your Foundry project.

## Same use-case, self-contained folders

Both examples implement the **same** demo — "Clara", a health-insurance member
assistant. Each folder keeps its own instructions and tools (so it reads
top-to-bottom on its own), while the sample **data is shared** in a root
`data/` folder:

| File | Location | What |
|---|---|---|
| `instructions.md` | each folder | The "Clara" persona / behaviour. |
| `tools.py` | each folder | Function tools (claims, coverage, providers, deductible) + dispatch. |
| `data.json` | [`data/`](data) (shared) | Mock sample data (no real member data / PHI). |

Each example converts its tool schemas into its own SDK's tool object
(`azure.ai.voicelive.FunctionTool` vs. `azure.ai.projects.FunctionToolParam`).

## Quick start

Pick one folder and follow its README. Run the scripts from **within** their
folder so the local `tools.py` / `data.json` / `instructions.md` are found:

- **[agent-mode/](agent-mode/README.md)** — create a Foundry agent, then talk to it.
- **[native-realtime/](native-realtime/README.md)** — talk to `gpt-realtime` directly.

```bash
cd agent-mode        # or: cd native-realtime
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # then fill in the values
az login
```

Then run the script named in that folder's README.

## Notes

- **Auth:** Agent mode requires Microsoft Entra ID (`az login`). Native mode
  accepts Entra ID **or** an API key.
- **Audio:** WSL2 has no audio devices — run on native Windows (or any machine
  with a mic and speakers). On Windows, `pip install pyaudio` uses a prebuilt
  wheel (no PortAudio compile).
- **Source of truth:** the official
  [`agent_v2_sample.py`](https://github.com/Azure/azure-sdk-for-python/blob/main/sdk/voicelive/azure-ai-voicelive/samples/agent_v2_sample.py)
  in the Azure SDK for Python repo.
