"""Speech-to-text client wrapper.

Today this only wraps Deepgram, but the interface is provider-agnostic.
A future version can add OpenAI Whisper, AssemblyAI, AWS Transcribe, etc.
by adding new branches and exposing them under the same STTClient interface.
"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger("bob_voice_sdk.stt")


class STTClient:
    """Async speech-to-text client.

    Today: wraps Deepgram's REST API.
    Future: same interface, multiple providers.

    Usage:
        stt = STTClient(provider="deepgram", api_key="...")
        transcript = await stt.transcribe(audio_bytes, mimetype="audio/webm")
    """

    def __init__(self, provider: str = "deepgram", api_key: str = "",
                 model: str = "nova-2", language: str = "en"):
        self.provider = provider.lower()
        self.api_key = api_key
        self.model = model
        self.language = language
        self._client: Any = None

        if not api_key:
            logger.warning(f"STTClient initialized with no API key (provider={provider})")

    def _get_deepgram(self):
        """Lazy import + cache the Deepgram client so the SDK doesn't
        require deepgram-sdk if the user picks a different provider."""
        if self._client is None:
            try:
                from deepgram import DeepgramClient
            except ImportError as e:
                raise ImportError(
                    "Deepgram backend requires `deepgram-sdk`. "
                    "Install with: pip install deepgram-sdk"
                ) from e
            self._client = DeepgramClient(self.api_key)
        return self._client

    async def transcribe(self, audio_data: bytes, mimetype: str = "audio/webm") -> str:
        """Transcribe a chunk of audio. Returns plain text.

        Args:
            audio_data: Raw audio bytes (webm, wav, mp3, etc.)
            mimetype: MIME type of the audio (e.g., 'audio/webm', 'audio/wav')

        Returns:
            Transcribed text. Empty string if transcription failed or
            the audio was silent.
        """
        if self.provider != "deepgram":
            raise NotImplementedError(
                f"STT provider '{self.provider}' not implemented yet. "
                f"Currently only 'deepgram' is supported."
            )

        try:
            client = self._get_deepgram()
            options = {
                "model": self.model,
                "smart_format": True,
                "language": self.language,
            }
            source = {"buffer": audio_data, "mimetype": mimetype}
            response = await asyncio.to_thread(
                lambda: client.listen.rest.v("1").transcribe_file(source, options)
            )
            return response.results.channels[0].alternatives[0].transcript or ""
        except (IndexError, AttributeError) as e:
            logger.warning(f"STT response missing expected fields: {e}")
            return ""
        except Exception as e:
            logger.error(f"STT transcription failed: {e}")
            return ""
