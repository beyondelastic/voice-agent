#!/usr/bin/env python
"""
voice_agent.py — Talk to a custom Microsoft Foundry agent with Azure Voice Live.

This is a minimal, well-commented example for the CURRENT GA SDK
(azure-ai-voicelive >= 1.2.0). The important change vs. the old beta docs:

    OLD (beta 1.2.0b1..b4):  connect(..., agent_config=AgentSessionConfig(...))
    NEW (GA 1.2.0):          connect(..., agent_name=..., project_name=...)

The agent is now selected with FLATTENED keyword arguments on connect(), and it
becomes the primary responder for the voice session. The SDK is async-only.

What this script does:
  1. Opens a WebSocket to Voice Live and attaches your Foundry agent.
  2. Streams microphone audio up, and plays the agent's spoken reply back.
  3. Handles barge-in (you can interrupt the agent by speaking).

Agent mode requires Microsoft Entra ID auth (run `az login` first).
API keys are NOT supported for agent connections.

Prerequisites (.env):
  AZURE_VOICELIVE_ENDPOINT, AGENT_NAME, AGENT_PROJECT_NAME

Run:
  python voice_agent.py
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import queue
import signal
import sys
from typing import Optional

import pyaudio
from dotenv import load_dotenv

from azure.identity.aio import DefaultAzureCredential
from azure.ai.voicelive.aio import VoiceLiveConnection, connect
from azure.ai.voicelive.models import (
    AzureStandardVoice,
    FunctionCallOutputItem,
    InputAudioFormat,
    Modality,
    OutputAudioFormat,
    RequestSession,
    ServerEventType,
    ServerVad,
)

# Tool dispatch lives alongside this script (tools.py, data.json). The tools
# themselves are configured on the Foundry agent (see create_agent.py); here we
# just execute the call the agent asks for and return the result.
from tools import run_tool

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("voice_agent")

# --- Configuration (from .env) ---------------------------------------------
ENDPOINT = os.environ.get("AZURE_VOICELIVE_ENDPOINT", "")
AGENT_NAME = os.environ.get("AGENT_NAME", "")
PROJECT_NAME = os.environ.get("AGENT_PROJECT_NAME", "")
AGENT_VERSION = os.environ.get("AGENT_VERSION")  # optional; None = latest
CONVERSATION_ID = os.environ.get("AGENT_CONVERSATION_ID")  # optional
VOICE = os.environ.get("AGENT_VOICE", "en-US-Ava:DragonHDLatestNeural")
# Leave unset to use the SDK's own default (2026-04-10 on GA 1.2.0,
# 2026-07-15 on the 1.3.0 preview). Only override to pin a specific API version.
API_VERSION = os.environ.get("AZURE_VOICELIVE_API_VERSION")

# Voice Live always uses 24 kHz, 16-bit, mono PCM audio.
SAMPLE_RATE = 24000
CHUNK_SIZE = 1200  # 50 ms of audio per chunk


class AudioProcessor:
    """Captures microphone audio and plays back the agent's audio.

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
            # Send each captured chunk to the service (base64-encoded PCM16).
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
        # Everything currently queued gets a lower seq_num than the new base,
        # so the playback callback discards it (used on barge-in).
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


class VoiceAgent:
    """Connects to a Foundry agent and runs the conversation loop."""

    def __init__(self, credential: DefaultAzureCredential):
        self.credential = credential
        self.connection: Optional[VoiceLiveConnection] = None
        self.audio: Optional[AudioProcessor] = None

    async def run(self) -> None:
        logger.info("Connecting to agent '%s' (project '%s')", AGENT_NAME, PROJECT_NAME)

        # *** The key part: select the Foundry agent via flattened keywords. ***
        # api_version is an explicit connect() parameter, independent of the SDK
        # version. Omit it to use the SDK default, or pin one to evaluate a newer
        # service API (e.g. 2026-07-15) against your agent.
        optional = {"api_version": API_VERSION} if API_VERSION else {}
        async with connect(
            endpoint=ENDPOINT,
            credential=self.credential,
            agent_name=AGENT_NAME,
            project_name=PROJECT_NAME,
            agent_version=AGENT_VERSION,       # optional
            conversation_id=CONVERSATION_ID,   # optional
            **optional,
        ) as connection:
            self.connection = connection
            self.audio = AudioProcessor(connection)

            await self._setup_session()
            self.audio.start_playback()

            print("\n" + "=" * 60)
            print("🎤 VOICE AGENT READY — start speaking (Ctrl+C to exit)")
            print("=" * 60 + "\n")

            try:
                async for event in connection:
                    await self._handle_event(event)
            finally:
                self.audio.shutdown()

    async def _setup_session(self) -> None:
        """Apply voice + turn-detection settings for this session.

        The agent supplies the instructions/behaviour; here we only configure
        the audio experience (which voice speaks, how turns are detected).
        """
        session = RequestSession(
            modalities=[Modality.TEXT, Modality.AUDIO],
            voice=AzureStandardVoice(name=VOICE),
            input_audio_format=InputAudioFormat.PCM16,
            output_audio_format=OutputAudioFormat.PCM16,
            # Server-side voice activity detection = automatic turn taking.
            turn_detection=ServerVad(threshold=0.5, prefix_padding_ms=300, silence_duration_ms=500),
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
            print(f"🤖 Agent: {event.get('transcript', '')}")

        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
            # User started talking — stop the agent's current playback (barge-in).
            print("🎤 Listening...")
            self.audio.skip_pending_audio()

        elif event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
            # A chunk of the agent's spoken reply — queue it for playback.
            self.audio.queue_audio(event.delta)

        elif event.type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            # The agent invoked one of its tools — run it and return the result.
            await self._handle_function_call(event)

        elif event.type == ServerEventType.RESPONSE_DONE:
            print("🎤 Ready for next input...")

        elif event.type == ServerEventType.ERROR:
            logger.error("Voice Live error: %s", event.error.message)

    async def _handle_function_call(self, event) -> None:
        """Run the tool the agent requested and send the result back."""
        output = run_tool(event.name, event.arguments)
        print(f"🛠️  {event.name}({event.arguments}) → {output}")

        assert self.connection is not None
        await self.connection.conversation.item.create(
            item=FunctionCallOutputItem(call_id=event.call_id, output=output)
        )
        await self.connection.response.create()


async def _run() -> None:
    missing = [n for n, v in
               (("AZURE_VOICELIVE_ENDPOINT", ENDPOINT),
                ("AGENT_NAME", AGENT_NAME),
                ("AGENT_PROJECT_NAME", PROJECT_NAME)) if not v]
    if missing:
        sys.exit(f"❌ Missing required environment variables: {', '.join(missing)}")

    # DefaultAzureCredential uses your `az login` session (Entra ID).
    credential = DefaultAzureCredential()
    try:
        await VoiceAgent(credential).run()
    finally:
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
