"""bob_voice_sdk — reusable voice loop primitives extracted from BOB Voice.

This package contains the building blocks of BOB Voice that aren't specific
to BOB the orchestrator. They can be used by any agent framework or chat
backend that needs:

- Real-time speech-to-text via Deepgram (STT module)
- Streaming text-to-speech via ElevenLabs (TTS module)
- Sentence-boundary chunking for low-latency audio playback
- A WebSocket bridge that ties them together

The goal: any agent framework should be able to `pip install bob-voice-sdk`,
plug in their own backend (a function that takes a message and returns a
streaming text response), and get a production-grade voice loop with minimal
glue code.

Status: pre-1.0. The API may change. The split between SDK and BOB-specific
glue is the proof-of-concept that the extraction is feasible. A real PyPI
publish is on the Tier 3 roadmap.

Public API:
    from bob_voice_sdk import STTClient, TTSClient, SentenceChunker
    from bob_voice_sdk import VoiceLoop  # high-level orchestrator

See README.md in this package for usage examples.
"""

from .stt import STTClient
from .tts import TTSClient
from .chunker import SentenceChunker

__version__ = "0.1.0-alpha"
__all__ = ["STTClient", "TTSClient", "SentenceChunker", "__version__"]
