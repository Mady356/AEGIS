"""
Camera-based pulse estimation (rPPG).

Pipeline:
  1. OpenCV captures frames from the default camera at 30 fps
  2. MediaPipe face mesh isolates the forehead and cheek ROIs
  3. Per-ROI green-channel average is appended to a 10-second rolling buffer
  4. Buffer is detrended, bandpass-filtered (0.7–4.0 Hz, 4th-order Butterworth)
  5. FFT identifies the dominant frequency, converted to BPM
  6. Exponential moving average (alpha=0.2) smooths the BPM stream
  7. Estimates broadcast at 2 Hz over WebSocket / SSE

The camera frame itself is never displayed to the UI and never persisted
to disk. Only ROI green-channel averages are processed in memory.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import AsyncIterator

try:
    import cv2
    import mediapipe as mp
    import numpy as np
    from scipy.signal import butter, filtfilt, detrend
except ImportError as exc:  # pragma: no cover
    raise RuntimeError(
        "rppg requires opencv-python-headless, mediapipe, numpy, and scipy. "
        "Install with: pip install opencv-python-headless mediapipe scipy"
    ) from exc


SAMPLE_RATE = 30        # fps
WINDOW_SEC = 10
WINDOW = SAMPLE_RATE * WINDOW_SEC

# Face landmark indices for forehead and cheeks (MediaPipe face_mesh)
FOREHEAD_IDX = [10, 67, 69, 104, 103, 67, 109, 10]
LCHEEK_IDX   = [50, 101, 116, 117, 118, 119, 100, 47]
RCHEEK_IDX   = [280, 330, 345, 346, 347, 348, 329, 277]


class RPPGStream:
    def __init__(self, camera_index: int = 0):
        self.cam = cv2.VideoCapture(camera_index)
        self.face_mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1, refine_landmarks=False,
            min_detection_confidence=0.6, min_tracking_confidence=0.6,
        )
        self.buf: deque[float] = deque(maxlen=WINDOW)
        self.bpm_ema: float = 0.0
        self.confidence: int = 0
        self.active = True

    async def stream(self) -> AsyncIterator[dict]:
        last_emit = 0.0
        while self.active:
            ok, frame = self.cam.read()
            if not ok:
                await asyncio.sleep(1.0 / SAMPLE_RATE); continue
            roi_avg = self._extract_roi_avg(frame)
            if roi_avg is not None:
                self.buf.append(roi_avg)
            if len(self.buf) >= SAMPLE_RATE * 4 and (time.monotonic() - last_emit) >= 0.5:
                bpm, conf = self._estimate_bpm()
                if bpm > 0:
                    yield {"bpm": round(bpm, 1), "confidence": conf, "t": int(time.time() * 1000)}
                    last_emit = time.monotonic()
            await asyncio.sleep(1.0 / SAMPLE_RATE)

    def _extract_roi_avg(self, frame_bgr) -> float | None:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return None
        h, w = frame_bgr.shape[:2]
        lm = results.multi_face_landmarks[0].landmark
        mask = np.zeros((h, w), dtype=np.uint8)
        for idx_set in (FOREHEAD_IDX, LCHEEK_IDX, RCHEEK_IDX):
            pts = np.array([(int(lm[i].x * w), int(lm[i].y * h)) for i in idx_set])
            cv2.fillPoly(mask, [pts], 255)
        green = frame_bgr[:, :, 1]
        return float(green[mask > 0].mean())

    def _estimate_bpm(self) -> tuple[float, int]:
        sig = np.array(self.buf, dtype=float)
        if len(sig) < SAMPLE_RATE * 4:
            return 0.0, 0
        sig = detrend(sig)
        b, a = butter(4, [0.7, 4.0], btype="bandpass", fs=SAMPLE_RATE)
        try:
            filt = filtfilt(b, a, sig)
        except Exception:
            return 0.0, 0
        fft = np.abs(np.fft.rfft(filt))
        freqs = np.fft.rfftfreq(len(filt), 1.0 / SAMPLE_RATE)
        # Look for peak in 0.7–4.0 Hz range
        band = (freqs >= 0.7) & (freqs <= 4.0)
        if not band.any() or fft[band].sum() == 0:
            return 0.0, 0
        peak_idx = np.argmax(fft * band)
        peak_freq = freqs[peak_idx]
        peak_power = fft[peak_idx]
        median_power = float(np.median(fft[band]))
        prominence = peak_power / max(median_power, 1e-9)
        bpm = peak_freq * 60.0
        # EMA smoothing
        if self.bpm_ema == 0:
            self.bpm_ema = bpm
        else:
            self.bpm_ema = 0.2 * bpm + 0.8 * self.bpm_ema
        if prominence < 2.0:    self.confidence = 1
        elif prominence < 4.0:  self.confidence = 2
        else:                   self.confidence = 3
        return self.bpm_ema, self.confidence

    def close(self) -> None:
        self.active = False
        try: self.cam.release()
        except Exception: pass
        try: self.face_mesh.close()
        except Exception: pass
