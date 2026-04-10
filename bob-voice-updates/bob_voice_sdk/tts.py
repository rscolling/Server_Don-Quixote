"""Text-to-speech client wrapper with caching.

Today this only wraps ElevenLabs, but the interface is provider-agnostic.
A future version can add OpenAI TTS, Coqui, PlayHT, AWS Polly, etc.

Includes a small in-memory LRU cache so identical sentences (greetings,
common phrases) don't get re-synthesized on every interaction. Cache uses
a SHA-256 hash of the input text as the key.
"""

import asyncio
import hashlib
import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger("bob_voice_sdk.tts")


class TTSClient:
    """Async text-to-speech client with built-in caching.

    Today: wraps ElevenLabs.
    Future: same interface, multiple providers.

    Usage:
        tts = TTSClient(provider="elevenlabs", api_key="...", voice_id="adam")
        audio_bytes = await tts.synthesize("Hello world")
    """

    def __init__(self, provider: str = "elevenlabs", api_key: str = "",
                 voice_id: str = "pNInz6obpgDQGcFmaJgB",
                 model_id: str = "eleven_turbo_v2_5",
                 output_format: str = "mp3_44100_128",
                 cache_size: int = 100):
        self.provider = provider.lower()
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.cache_size = cache_size
        self._client: Any = None
        self._cache: OrderedDict[str, bytes] = OrderedDict()

        if not api_key:
            logger.warning(f"TTSClient initialized with no API key (provider={provider})")

    def _get_elevenlabs(self):
        """Lazy import + cache the ElevenLabs client."""
        if self._client is None:
            try:
                from elevenlabs.client import ElevenLabs
            except ImportError as e:
                raise ImportError(
                    "ElevenLabs backend requires `elevenlabs`. "
                    "Install with: pip install elevenlabs"
                ) from e
            self._client = ElevenLabs(api_key=self.api_key)
        return self._client

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _cache_get(self, text: str) -> bytes | None:
        key = self._cache_key(text)
        if key in self._cache:
            # LRU: move to end on access
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _cache_put(self, text: str, audio: bytes) -> None:
        key = self._cache_key(text)
        self._cache[key] = audio
        self._cache.move_to_end(key)
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)

    def _synthesize_blocking(self, text: str) -> bytes:
        """Generate TTS audio synchronously. Returns complete MP3 bytes."""
        if self.provider != "elevenlabs":
            raise NotImplementedError(
                f"TTS provider '{self.provider}' not implemented yet. "
                f"Currently only 'elevenlabs' is supported."
            )
        client = self._get_elevenlabs()
        audio_gen = client.text_to_speech.convert(
            text=text,
            voice_id=self.voice_id,
            model_id=self.model_id,
            output_format=self.output_format,
        )
        chunks = [chunk for chunk in audio_gen if chunk]
        return b"".join(chunks)

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to audio bytes (cached when possible).

        Returns audio in the configured output format (default MP3 44.1kHz 128kbps).
        Returns empty bytes if synthesis fails — never raises so the caller
        can degrade gracefully.
        """
        if not text or not text.strip():
            return b""

        cached = self._cache_get(text)
        if cached is not None:
            return cached

        try:
            audio = await asyncio.to_thread(self._synthesize_blocking, text)
            self._cache_put(text, audio)
            return audio
        except Exception as e:
            logger.error(f"TTS synthesis failed for text {text[:60]!r}: {e}")
            return b""

    def cache_stats(self) -> dict:
        """Return cache stats for diagnostics."""
        return {
            "cache_size": len(self._cache),
            "cache_max": self.cache_size,
            "cache_bytes": sum(len(v) for v in self._cache.values()),
        }

    def clear_cache(self) -> None:
        self._cache.clear()
