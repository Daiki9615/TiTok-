"""音声認識（F-04, F-05）。faster-whisper を使い、GPU があれば GPU、なければ CPU で動かす。"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def has_cuda() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


class WhisperTranscriber:
    def __init__(self, model_size: str | None = None, device: str | None = None):
        self.device = device or ("cuda" if has_cuda() else "cpu")
        # GPU なら精度重視の large-v3、CPU なら速度重視の small
        self.model_size = model_size or ("large-v3" if self.device == "cuda" else "small")
        self._model = None

    @property
    def name(self) -> str:
        return f"faster-whisper {self.model_size} ({self.device})"

    def _load(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        try:
            compute = "float16" if self.device == "cuda" else "int8"
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=compute)
        except Exception:
            if self.device != "cuda":
                raise
            # GPU で読み込めない場合は CPU に切り替える
            self.device, self.model_size = "cpu", "small"
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio_path: Path) -> dict[str, Any]:
        model = self._load()
        segments, info = model.transcribe(
            str(audio_path),
            language="ja",
            beam_size=5,
            vad_filter=True,
            word_timestamps=True,
        )
        segs = []
        for s in segments:  # 全編を最後まで読む
            words = [
                {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word}
                for w in (s.words or [])
            ]
            segs.append(
                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(), "words": words}
            )
        return {
            "text": "".join(s["text"] for s in segs),
            "segments": segs,
            "audio_duration": round(getattr(info, "duration", 0.0) or 0.0, 2),
            "model": self.name,
        }
