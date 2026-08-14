#!/usr/bin/env python
"""
voice_realtime.py — Talk to a native gpt-realtime model with Azure Voice Live.

This is the NATIVE (speech-to-speech) counterpart to ../agent-mode. Instead of a
managed Foundry agent, you connect straight to a native audio model
(`gpt-realtime`). One model hears your audio and speaks its reply directly —
lowest latency, most natural voice. There is no separate STT/TTS step.

Customization lives IN THIS FILE:
  - `instructions=` sets the persona/behaviour (the "custom" part).
  - You can add `tools=[...]` for function calling / MCP if needed.

Key difference vs. agent mode:
    agent-mode:  connect(..., agent_name=..., project_name=...)   # cascaded
    native:      connect(..., model="gpt-realtime")               # speech-to-speech

Voice Live is fully managed — you do NOT deploy gpt-realtime yourself.

Auth: works with either Microsoft Entra ID (`az login`, default) or an API key
(set AZURE_VOICELIVE_API_KEY). Native mode supports both.

Prerequisites (.env):
  AZURE_VOICELIVE_ENDPOINT

Run:
  python voice_realtime.py
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import queue
import signal
import sys
from typing import Optional, Union

import pyaudio
from dotenv import load_dotenv

from azure.core.credentials import AzureKeyCredential
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential
from azure.ai.voicelive.aio import VoiceLiveConnection, connect
from azure.ai.voicelive.models import (
    AudioInputTranscriptionOptions,
    FunctionCallOutputItem,
    FunctionTool,
    InputAudioFormat,
    Modality,
    OutputAudioFormat,
    RequestSession,
    ServerEventType,
    ServerVad,
    ToolChoiceLiteral,
)

# Tools live alongside this script (tools.py, data.json).
from tools import TOOL_SCHEMAS, run_tool

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))

# Persona lives in instructions.md next to this script.
with open(os.path.join(_HERE, "instructions.md"), encoding="utf-8") as _f:
    _DEFAULT_INSTRUCTIONS = _f.read().strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("voice_realtime")

# --- Configuration (from .env) ---------------------------------------------
ENDPOINT = os.environ.get("AZURE_VOICELIVE_ENDPOINT", "")
# Native speech-to-speech model. No deployment needed — Voice Live manages it.
MODEL = os.environ.get("AZURE_VOICELIVE_MODEL", "gpt-realtime")
# A native model voice (alloy, echo, fable, onyx, nova, shimmer, marin, cedar).
VOICE = os.environ.get("VOICE_NAME", "alloy")
# Behaviour comes from instructions.md. Set INSTRUCTIONS in .env to override.
INSTRUCTIONS = os.environ.get("INSTRUCTIONS") or _DEFAULT_INSTRUCTIONS
# Optional API key. If unset, Entra ID (az login) is used.
API_KEY = os.environ.get("AZURE_VOICELIVE_API_KEY")
# Leave unset to use the SDK's own default API version.
API_VERSION = os.environ.get("AZURE_VOICELIVE_API_VERSION")

# Voice Live always uses 24 kHz, 16-bit, mono PCM audio.
SAMPLE_RATE = 24000
CHUNK_SIZE = 1200  # 50 ms of audio per chunk

# Build Voice Live tool objects from the shared, SDK-agnostic schemas.
INSURANCE_TOOLS = [
    FunctionTool(name=s["name"], description=s["description"], parameters=s["parameters"])
    for s in TOOL_SCHEMAS
]


class AudioProcessor:
    """Captures microphone audio and plays back the model's audio.

    PyAudio runs its own callback threads, so audio I/O never blocks the async
    event loop. Playback uses sequence numbers so we can cleanly drop queued
    audio when the user interrupts (barge-in).
    """

    class _Packet:
        def __init__(self, seq_num: int, data: Optional[bytes]):
            self.seq_num = seq_num
            self.data = data

    def __init__(self, connection: VoiceLiveConnection):
        self.connection = connection
        self.audio = pyaudio.PyAudio()
        self.loop = asyncio.get_running_loop()

        self.input_stream: Optional[pyaudio.Stream] = None
        self.output_stream: Optional[pyaudio.Stream] = None

        self.playback_queue: "queue.Queue[AudioProcessor._Packet]" = queue.Queue()
        self.playback_base = 0  # packets with a lower seq_num are skipped
        self.next_seq_num = 0

    # --- Capture (microphone -> service) -----------------------------------
    def start_capture(self) -> None:
        if self.input_stream:
            return

        def _callback(in_data, _frames, _time, _status):
            audio_b64 = base64.b64encode(in_data).decode("utf-8")
            asyncio.run_coroutine_threadsafe(
                self.connection.input_audio_buffer.append(audio=audio_b64), self.loop
            )
            return (None, pyaudio.paContinue)

        self.input_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
            stream_callback=_callback,
        )
        logger.info("Microphone capture started")

    # --- Playback (service -> speakers) ------------------------------------
    def start_playback(self) -> None:
        if self.output_stream:
            return

        remaining = bytes()

        def _callback(_in_data, frame_count, _time, _status):
            nonlocal remaining
            frame_count *= pyaudio.get_sample_size(pyaudio.paInt16)

            out = remaining[:frame_count]
            remaining = remaining[frame_count:]

            while len(out) < frame_count:
                try:
                    packet = self.playback_queue.get_nowait()
                except queue.Empty:
                    out += bytes(frame_count - len(out))  # fill with silence
                    continue

                if not packet or not packet.data:
                    return (out, pyaudio.paComplete)  # end of stream

                if packet.seq_num < self.playback_base:
                    remaining = bytes()  # dropped due to barge-in
                    continue

                take = frame_count - len(out)
                out += packet.data[:take]
                remaining = packet.data[take:]

            return (out, pyaudio.paContinue)

        self.output_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            output=True,
            frames_per_buffer=CHUNK_SIZE,
            stream_callback=_callback,
        )
        logger.info("Speaker playback ready")

    def _next_seq(self) -> int:
        seq = self.next_seq_num
        self.next_seq_num += 1
        return seq

    def queue_audio(self, data: Optional[bytes]) -> None:
        self.playback_queue.put(AudioProcessor._Packet(self._next_seq(), data))

    def skip_pending_audio(self) -> None:
        self.playback_base = self._next_seq()

    def shutdown(self) -> None:
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None
        if self.output_stream:
            self.skip_pending_audio()
            self.queue_audio(None)
            self.output_stream.stop_stream()
            self.output_stream.close()
            self.output_stream = None
        self.audio.terminate()
        logger.info("Audio cleaned up")


class RealtimeVoice:
    """Connects to a native gpt-realtime model and runs the conversation loop."""

    def __init__(self, credential: Union[AzureKeyCredential, AsyncTokenCredential]):
        self.credential = credential
        self.connection: Optional[VoiceLiveConnection] = None
        self.audio: Optional[AudioProcessor] = None

    async def run(self) -> None:
        logger.info("Connecting to native model '%s'", MODEL)

        # *** The key part: connect to a native audio model, not an agent. ***
        optional = {"api_version": API_VERSION} if API_VERSION else {}
        async with connect(
            endpoint=ENDPOINT,
            credential=self.credential,
            model=MODEL,
            **optional,
        ) as connection:
            self.connection = connection
            self.audio = AudioProcessor(connection)

            await self._setup_session()
            self.audio.start_playback()

            print("\n" + "=" * 60)
            print(f"🎤 REALTIME VOICE READY ({MODEL}) — start speaking (Ctrl+C to exit)")
            print("=" * 60 + "\n")

            try:
                async for event in connection:
                    await self._handle_event(event)
            finally:
                self.audio.shutdown()

    async def _setup_session(self) -> None:
        """Configure the native session.

        Unlike agent mode, the behaviour (`instructions`) is set here in code.
        The voice is a native model voice (e.g. 'alloy'), not an Azure TTS voice.
        """
        session = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            instructions=INSTRUCTIONS,       # ← custom behaviour, defined in code
            voice=VOICE,                     # native model voice (string)
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            # Server-side voice activity detection = automatic turn taking.
            turn_detection=ServerVad(threshold=0.5, prefix_padding_ms=300, silence_duration_ms=500),
            # Transcribe the member's speech so we can print "👤 You: ...".
            input_audio_transcription=AudioInputTranscriptionOptions(model="whisper-1"),
            # Health-insurance tools; the model calls them when useful.
            tools=INSURANCE_TOOLS,
            tool_choice=ToolChoiceLiteral.AUTO,
        )
        assert self.connection is not None
        await self.connection.session.update(session=session)
        logger.info("Session configured")

    async def _handle_event(self, event) -> None:
        assert self.audio is not None

        if event.type == ServerEventType.SESSION_UPDATED:
            # Session is ready — start listening to the microphone.
            self.audio.start_capture()

        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
            print(f"👤 You:   {event.get('transcript', '')}")

        elif event.type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
            print(f"🤖 Model: {event.get('transcript', '')}")

        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            # User started talking — stop the model's current playback (barge-in).
            print("🎤 Listening...")
            self.audio.skip_pending_audio()

        elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
            # A chunk of the model's spoken reply — queue it for playback.
            self.audio.queue_audio(event.delta)

        elif event.type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            # The model wants to call one of our tools.
            await self._handle_function_call(event)

        elif event.type == ServerEventType.RESPONSE_DONE:
            print("🎤 Ready for next input...")

        elif event.type == ServerEventType.ERROR:
            logger.error("Voice Live error: %s", event.error.message)

    async def _handle_function_call(self, event) -> None:
        """Run the requested tool and send its result back to the model."""
        output = run_tool(event.name, event.arguments)
        print(f"🛠️  {event.name}({event.arguments}) → {output}")

        assert self.connection is not None
        # Return the result (output is a JSON string), then ask the model to
        # continue speaking with the tool result in context.
        await self.connection.conversation.item.create(
            item=FunctionCallOutputItem(call_id=event.call_id, output=output)
        )
        await self.connection.response.create()


async def _run() -> None:
    if not ENDPOINT:
        sys.exit("❌ Missing required environment variable: AZURE_VOICELIVE_ENDPOINT")

    # Native mode accepts an API key or Entra ID. Prefer key if provided.
    credential: Union[AzureKeyCredential, AsyncTokenCredential]
    if API_KEY:
        credential = AzureKeyCredential(API_KEY)
        logger.info("Using API key credential")
    else:
        credential = DefaultAzureCredential()
        logger.info("Using DefaultAzureCredential (az login)")

    try:
        await RealtimeVoice(credential).run()
    finally:
        if isinstance(credential, AsyncTokenCredential):
            await credential.close()


def main() -> None:
    signal.signal(signal.SIGINT, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")


if __name__ == "__main__":
    main()
