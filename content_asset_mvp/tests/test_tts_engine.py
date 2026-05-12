"""Unit tests for ``app.tts_engine``.

Focus is on the deterministic, network-free pieces:

* ``_text_to_doubao_ssml`` — the SSML payload builder we added to push
  Doubao BigTTS' per-track LRA from ~4.3 LU back up to ≥ 6 LU. The
  builder is the only meaningful piece of logic in the module that does
  NOT require network credentials, so it's the one place where we can
  put a real regression net.
* ``_slow_wrap_numbers_and_brands`` — the "weight" prosody helper that
  slows down number+unit reads.

We deliberately do NOT test the network paths here. Those are exercised
by the live render smoke (``output/yt_*/03_audio/tts_status.json``
records ``ssml_status.applied=True`` when the wire format is accepted)
and by ``app.audio_mastering`` regressions on LUFS/LRA.
"""
from __future__ import annotations

import re

from app.tts_engine import (
    _segment_to_ssml,
    _slow_wrap_numbers_and_brands,
    _text_to_doubao_ssml,
)


def test_empty_input_returns_empty_string():
    """Empty input must round-trip to empty so callers know to fall back."""
    assert _text_to_doubao_ssml("") == ""
    assert _text_to_doubao_ssml("   \n\n  ") == ""


def test_wraps_with_speak_root():
    out = _text_to_doubao_ssml("你好。")
    assert out.startswith("<speak>")
    assert out.endswith("</speak>")


def test_sentence_punctuation_inserts_calibrated_break():
    """Sentence-final punctuation triggers a 120ms break (small extra pause)."""
    out = _text_to_doubao_ssml("第一句。第二句！第三句？")
    assert out.count('<break time="120ms"/>') == 3


def test_comma_punctuation_does_not_insert_break():
    """Comma breaks were measured as the dominant silence-bloat source.

    We rely on the underlying engine's natural comma inflection instead —
    only the trailing sentence-final 。 should trigger a break tag.
    """
    out = _text_to_doubao_ssml("一段，两段、三段；四段。")
    assert '<break time="0ms"/>' not in out
    assert out.count("<break") == 1


def test_paragraph_split_inserts_paragraph_break():
    """Blank-line separated paragraphs get a 380ms break joiner."""
    out = _text_to_doubao_ssml("段一。\n\n段二。")
    assert '<break time="380ms"/>' in out
    # Per-paragraph trailing breaks still happen.
    assert out.count('<break time="120ms"/>') == 2


def test_numbers_and_units_get_slow_prosody():
    """Number + Chinese/English unit tokens get wrapped in slow prosody."""
    out = _text_to_doubao_ssml("项目有 8 万 star，售价 200 美元。")
    # Both number+unit phrases should be wrapped.
    assert out.count('<prosody rate="slow">') == 2
    assert "8 万" in out
    assert "200 美元" in out


def test_xml_special_chars_are_escaped():
    """Avoid breaking Doubao's XML parser on script content."""
    out = _text_to_doubao_ssml("代码 <html> & 数据 (&)")
    assert "&lt;html&gt;" in out
    assert "&amp;" in out
    # Make sure we didn't accidentally escape our own SSML tags.
    assert "<speak>" in out
    assert "</speak>" in out


def test_segment_without_punctuation_has_no_break():
    """Trailing-punctuation-less segment renders the body without a break."""
    rendered = _segment_to_ssml("hello world")
    assert "<break" not in rendered
    assert "hello world" in rendered


def test_segment_strips_outer_whitespace():
    rendered = _segment_to_ssml("   hi 。   ")
    # The space between body and punctuation is preserved verbatim
    # because Doubao reads "  hi 。" as "hi" with a tiny pause.
    assert rendered.startswith("hi 。") or rendered.startswith("hi。")


def test_slow_wrap_only_targets_recognised_units():
    """We deliberately skip raw integers like ``Top 5`` so we don't over-wrap."""
    plain = "排名 Top 5 的开源项目"
    wrapped = _slow_wrap_numbers_and_brands(plain)
    assert "<prosody" not in wrapped


def test_slow_wrap_handles_decimal_and_units():
    wrapped = _slow_wrap_numbers_and_brands("用了 1.5 小时")
    assert '<prosody rate="slow">' in wrapped
    assert "1.5 小时" in wrapped


def test_full_sample_resembles_expected_shape():
    """End-to-end smoke: typical narration block emits sentence + paragraph breaks."""
    sample = (
        "Peter 在摩洛哥旅行时，AI 立即识别了问题。这件事真的很疯狂！\n\n"
        "它能在 8 万 star 项目里直接跑通，200 美元就够了。"
    )
    out = _text_to_doubao_ssml(sample)
    # Sentence + paragraph breaks must both appear; comma break must NOT.
    for ms in (120, 380):
        assert f'<break time="{ms}ms"/>' in out, f"missing {ms}ms break"
    # Slow prosody must wrap both number+unit tokens.
    assert out.count('<prosody rate="slow">') == 2
    # And it must be a single legal SSML root.
    assert re.match(r"^<speak>.+</speak>$", out, flags=re.DOTALL) is not None
