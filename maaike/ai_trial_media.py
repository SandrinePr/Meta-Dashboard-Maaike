"""Prepare local media for the AI trial without calling a paid model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEDIA_ROOT = PROJECT_ROOT / "data" / "ai_trial_media"
_MAX_BYTES = 12_000_000
_USER_AGENT = "MetaDashboard2-AITrial/1.0"


def _kind_of_url(url: str, content_type: str = "") -> str:
    lower = url.lower()
    ct = (content_type or "").lower()
    if "video/" in ct or any(x in lower for x in (".mp4", ".mov", ".m4v", "/v/t2/", "/t16/")):
        return "video"
    if "image/" in ct or any(x in lower for x in (".jpg", ".jpeg", ".png", ".webp", "stp=dst-jpg", "t51.")):
        return "image"
    if "scontent" in lower and ".mp4" not in lower:
        return "image"
    return "unknown"


def classify_urls(urls: list[str]) -> list[dict[str, Any]]:
    out = []
    for index, url in enumerate(urls, start=1):
        out.append(
            {
                "index": index,
                "url": url,
                "host": urlparse(url).netloc,
                "guessed_kind": _kind_of_url(url),
            }
        )
    return out


def _download(url: str, dest: Path) -> dict[str, Any]:
    if not url.startswith("https://"):
        return {"ok": False, "error": "Alleen https-media van deze klant wordt opgehaald.", "path": None}
    try:
        response = requests.get(url, timeout=45, headers={"User-Agent": _USER_AGENT}, stream=True)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip()
        data = response.content
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Download mislukt: {exc.__class__.__name__}", "path": None}
    if not data:
        return {"ok": False, "error": "Leeg mediabestand.", "path": None}
    if len(data) > _MAX_BYTES:
        return {"ok": False, "error": "Bestand te groot voor lokale proefvoorbereiding.", "path": None}
    kind = _kind_of_url(url, content_type)
    suffix = ".mp4" if kind == "video" else ".jpg"
    if "png" in content_type:
        suffix = ".png"
    elif "webp" in content_type:
        suffix = ".webp"
    dest = dest.with_suffix(suffix)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {
        "ok": True,
        "error": None,
        "path": dest.relative_to(PROJECT_ROOT).as_posix(),
        "bytes": len(data),
        "content_type": content_type,
        "kind": kind,
    }


def sample_video_timestamps(duration_s: float | None, *, max_frames: int = 12) -> list[float]:
    """Dense first 3s + frames spread across the rest of the video. Cap total frames."""
    if duration_s is None or duration_s <= 0:
        return [0.0, 1.0, 2.0, 3.0]
    early = [t for t in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0) if t <= duration_s + 1e-6]
    rest: list[float] = []
    if duration_s > 3.5:
        remaining = duration_s - 3.0
        budget = max(0, max_frames - len(early))
        steps = min(budget, max(2, int(remaining / 4)))
        for i in range(1, steps + 1):
            ts = 3.0 + (remaining * i / (steps + 1))
            if ts < duration_s - 0.05:
                rest.append(round(ts, 2))
        end = round(max(0.0, duration_s - 0.25), 2)
        if end > 3.0 and (not rest or abs(rest[-1] - end) > 0.4):
            rest.append(end)
    stamps = sorted({round(t, 2) for t in early + rest})
    return stamps[:max_frames]


def _extract_video_frames(video_path: Path, out_dir: Path, *, label: str = "video") -> dict[str, Any]:
    """Extract timestamped frames across the full clip via imageio-ffmpeg (no paid API)."""
    try:
        import imageio.v2 as iio
        from PIL import Image
        import numpy as np
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"Frame-extractie vereist imageio/Pillow ({exc.__class__.__name__}).",
            "frames": [],
            "audio_extracted": False,
            "full_video_bytes_ready": False,
            "analysis_mode": "unavailable",
        }
    frames: list[dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = None
    fps = 25.0
    try:
        reader = iio.get_reader(video_path, format="FFMPEG")
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Video kon niet worden geopend ({exc.__class__.__name__}).",
            "frames": [],
            "audio_extracted": False,
            "full_video_bytes_ready": video_path.is_file(),
            "analysis_mode": "unavailable",
        }
    try:
        meta = reader.get_meta_data() or {}
        duration = float(meta["duration"]) if meta.get("duration") is not None else None
        fps = float(meta.get("fps") or 25.0) or 25.0
        timestamps = sample_video_timestamps(duration)
        for ts in timestamps:
            if duration is not None and ts > duration:
                continue
            try:
                index = max(0, int(ts * fps))
                frame = reader.get_data(index)
                arr = np.asarray(frame)
                if arr.ndim == 3 and arr.shape[2] > 3:
                    arr = arr[:, :, :3]
                img = Image.fromarray(arr.astype("uint8"))
                name = f"frame_{ts:.2f}s.jpg"
                target = out_dir / name
                img.save(target, format="JPEG", quality=85)
                frames.append(
                    {
                        "timestamp_s": ts,
                        "ok": True,
                        "error": None,
                        "path": target.relative_to(PROJECT_ROOT).as_posix(),
                        "width": img.width,
                        "height": img.height,
                        "label": label,
                    }
                )
            except Exception as exc:
                frames.append(
                    {
                        "timestamp_s": ts,
                        "ok": False,
                        "error": str(exc.__class__.__name__),
                        "path": None,
                        "label": label,
                    }
                )
    finally:
        try:
            reader.close()
        except Exception:
            pass
    ok_frames = [f for f in frames if f.get("ok")]
    video_bytes = video_path.stat().st_size if video_path.is_file() else 0
    # OpenAI-compat route used by this app sends images (+ optional input_audio), not native Gemini video parts.
    # Local full video file is kept for future native File API use; trial analysis uses timestamped frames.
    return {
        "ok": bool(ok_frames),
        "error": None if ok_frames else "Geen frames kunnen uitlezen.",
        "frames": frames,
        "duration_s": duration,
        "audio_extracted": False,
        "full_video_bytes_ready": video_bytes > 0,
        "video_bytes": video_bytes,
        "video_path": video_path.relative_to(PROJECT_ROOT).as_posix() if video_path.is_file() else None,
        "analysis_mode": "full_duration_frames" if ok_frames else "unavailable",
        "note": (
            f"Frames verspreid over de hele video ({len(ok_frames)} stuks, extra dicht in 0–3s). "
            "Beweging tussen frames is niet volledig bekeken. Geen audio/transcript → gesproken hook onbekend. "
            "Dit is géén claim van volledige videoanalyse. Native Gemini ondersteunt video/audio; "
            "de huidige OpenAI-compatibele route stuurt frames als afbeeldingen."
            if ok_frames
            else "Frame-extractie mislukt; alleen thumbnail/caption bruikbaar."
        ),
    }


# Backwards-compatible alias
def _extract_reel_frames(video_path: Path, out_dir: Path) -> dict[str, Any]:
    return _extract_video_frames(video_path, out_dir, label="reel")


def prepare_post_media(
    *,
    client_id: int,
    post_id: int,
    role: str,
    content_kind: str | None,
    media_urls: list[str],
    local_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Download/prepare available media for one trial post and describe what AI can see."""
    base = MEDIA_ROOT / f"client_{client_id}" / f"post_{post_id}"
    base.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, Any]] = []
    images_for_model: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    source_note = "meta_urls"

    # Uploaded local assets take precedence when present (works without Meta).
    if local_assets:
        source_note = "uploads"
        for item in local_assets:
            path = item.get("path")
            kind = item.get("kind")
            entry = {
                "index": item.get("index"),
                "kind": kind,
                "ok": True,
                "error": None,
                "path": path,
                "bytes": item.get("bytes"),
                "host": "local-upload",
                "source": "upload",
            }
            downloaded.append(entry)
            if kind == "image":
                images_for_model.append(
                    {
                        "index": item.get("index"),
                        "role": "carousel_slide" if role == "carousel" else ("thumbnail" if role == "reel" else "image"),
                        "path": path,
                        "bytes": item.get("bytes"),
                        "source": "upload",
                    }
                )
            elif kind == "video":
                videos.append(entry)
    else:
        classified = classify_urls(media_urls)
        for item in classified:
            stem = base / f"part_{item['index']:02d}"
            result = _download(item["url"], stem)
            entry = {**item, **result, "source": "meta_url"}
            downloaded.append(entry)
            if result.get("ok") and result.get("kind") == "image":
                images_for_model.append(
                    {
                        "index": item["index"],
                        "role": "carousel_slide" if role == "carousel" else ("thumbnail" if role == "reel" else "image"),
                        "path": result["path"],
                        "bytes": result["bytes"],
                        "source": "meta_url",
                    }
                )
            elif result.get("ok") and result.get("kind") == "video":
                videos.append(entry)

    missing: list[str] = []
    limitations: list[str] = []
    reel_frames: dict[str, Any] | None = None
    carousel_video_frames: list[dict[str, Any]] = []
    coverage = "none"
    videos_for_model: list[dict[str, Any]] = []

    if role == "image":
        if images_for_model:
            coverage = "image_and_caption"
        else:
            missing.append("afbeelding")
            limitations.append("Geen bereikbare afbeelding; alleen caption zou overblijven.")
            coverage = "caption_only"
    elif role == "carousel":
        image_parts = [d for d in downloaded if d.get("ok") and d.get("kind") == "image"]
        video_parts = [d for d in downloaded if d.get("ok") and d.get("kind") == "video"]
        # Keep original order: for each downloaded part, images go as-is; videos → frames with timestamps.
        ordered_model: list[dict[str, Any]] = []
        for d in downloaded:
            if not d.get("ok"):
                continue
            if d.get("kind") == "image":
                match = next((i for i in images_for_model if i.get("path") == d.get("path")), None)
                if match:
                    ordered_model.append(match)
            elif d.get("kind") == "video" and d.get("path"):
                video_file = PROJECT_ROOT / d["path"]
                extracted = _extract_video_frames(
                    video_file,
                    base / f"carousel_video_{d.get('index', 0):02d}",
                    label=f"carousel_video_{d.get('index')}",
                )
                carousel_video_frames.append(extracted)
                videos_for_model.append(
                    {
                        "index": d.get("index"),
                        "path": d.get("path"),
                        "bytes": d.get("bytes"),
                        "duration_s": extracted.get("duration_s"),
                        "sent_as": "timestamped_frames",
                        "native_video_bytes_to_openai_compat": False,
                    }
                )
                for fr in extracted.get("frames") or []:
                    if fr.get("ok") and fr.get("path"):
                        ordered_model.append(
                            {
                                "index": d.get("index"),
                                "role": "carousel_video_frame",
                                "path": fr["path"],
                                "timestamp_s": fr.get("timestamp_s"),
                                "bytes": (PROJECT_ROOT / fr["path"]).stat().st_size
                                if (PROJECT_ROOT / fr["path"]).exists()
                                else None,
                                "source": d.get("source"),
                                "parent_slide": d.get("index"),
                            }
                        )
                if extracted.get("ok"):
                    limitations.append(
                        f"Videoslide {d.get('index')}: frames over de hele clip "
                        f"({extracted.get('duration_s')}s); beweging tussen frames niet volledig bekeken; geen audio."
                    )
                else:
                    missing.append(f"videoslide {d.get('index')} frames")
                    limitations.append(
                        f"Videoslide {d.get('index')}: {extracted.get('error') or 'frame-extractie mislukt'}."
                    )
        images_for_model = ordered_model
        if images_for_model:
            coverage = "carousel_images_and_video_frames" if video_parts else "carousel_images"
            expected_parts = len(local_assets) if local_assets else len(media_urls)
            got_parts = len([d for d in downloaded if d.get("ok")])
            if expected_parts and got_parts < expected_parts:
                missing.append(f"{expected_parts - got_parts} van {expected_parts} onderdelen niet beschikbaar")
        else:
            missing.append("carrouselslides")
            coverage = "caption_only"
            limitations.append("Geen carrouselmedia beschikbaar.")
    elif role == "reel":
        thumb = [i for i in images_for_model if i.get("role") == "thumbnail" or i.get("role") == "image"]
        if videos:
            video_file = PROJECT_ROOT / videos[0]["path"]
            reel_frames = _extract_video_frames(video_file, base / "frames", label="reel")
            videos_for_model.append(
                {
                    "index": videos[0].get("index"),
                    "path": videos[0].get("path"),
                    "bytes": videos[0].get("bytes"),
                    "duration_s": reel_frames.get("duration_s"),
                    "sent_as": "timestamped_frames",
                    "native_video_bytes_to_openai_compat": False,
                }
            )
            for fr in reel_frames.get("frames") or []:
                if fr.get("ok") and fr.get("path"):
                    images_for_model.append(
                        {
                            "index": len(images_for_model) + 1,
                            "role": "reel_frame",
                            "path": fr["path"],
                            "timestamp_s": fr.get("timestamp_s"),
                            "bytes": (PROJECT_ROOT / fr["path"]).stat().st_size
                            if (PROJECT_ROOT / fr["path"]).exists()
                            else None,
                        }
                    )
            if reel_frames.get("ok"):
                coverage = "reel_full_duration_frames"
                limitations.append(reel_frames.get("note") or "")
                limitations.append("Geen audio/transcript → gesproken tekst/hook blijft onbekend.")
                limitations.append(
                    "Native Gemini API ondersteunt video+audio; deze app-route (OpenAI-compat) stuurt "
                    "timestamped frames als afbeeldingen — geen claim van volledige videoanalyse."
                )
            else:
                coverage = "reel_thumbnail_only" if thumb else "caption_only"
                limitations.append(reel_frames.get("error") or "Frame-extractie mislukt.")
                limitations.append("Thumbnail/omslagfoto is geen volledige reelanalyse.")
                limitations.append("Gesproken hook onbekend zonder audio/transcript.")
        else:
            coverage = "reel_thumbnail_only" if thumb else "caption_only"
            missing.append("video")
            limitations.append("Geen video beschikbaar; thumbnail is geen volledige reelanalyse.")
            limitations.append("Gesproken hook onbekend.")
    else:
        coverage = "unknown_role"

    limitations = [lim for lim in limitations if lim]
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "urls": media_urls,
                "role": role,
                "source": source_note,
                "paths": [i.get("path") for i in images_for_model],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "client_id": client_id,
        "post_id": post_id,
        "role": role,
        "content_kind": content_kind,
        "coverage": coverage,
        "media_source": source_note,
        "media_url_count": len(media_urls),
        "downloaded": [
            {
                "index": d["index"],
                "kind": d.get("kind"),
                "ok": d.get("ok"),
                "error": d.get("error"),
                "path": d.get("path"),
                "bytes": d.get("bytes"),
                "host": d.get("host"),
                "source": d.get("source"),
            }
            for d in downloaded
        ],
        "images_for_model": images_for_model,
        "videos_for_model": videos_for_model,
        "video_count": len(videos),
        "reel_frames": reel_frames,
        "carousel_video_frames": carousel_video_frames,
        "missing": missing,
        "limitations": limitations,
        "can_send_to_model": bool(images_for_model),
        "full_video_to_model": False,
        "audio_to_model": False,
        "analysis_mode": (
            (reel_frames or {}).get("analysis_mode")
            if role == "reel"
            else ("carousel_with_video_frames" if carousel_video_frames else "images")
        ),
        "fingerprint": fingerprint,
        "provider_route_note": (
            "Gemini 3.5 Flash-Lite ondersteunt text/image/video/audio/PDF via de native Gemini API. "
            "Deze app gebruikt de OpenAI-compatibele chat/completions-route: afbeeldingen (frames) "
            "en optioneel input_audio; ruwe videobytes gaan in deze proef niet mee."
        ),
    }
