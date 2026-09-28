"""Anti-service control vector for the local model (owner request, 2026-09-28).

The persona is right and the architecture works (cloud01); what the local
4B cannot shed is its instruction-tuned assistant default: handing the turn
back, closing offers, service phrases (persona01, arch01: hand-back 0.61–0.73
under 15+ prompt variants). This builds a steering direction from the model's
OWN replies, contrastive-activation-addition style: the same context shows one
of its clean replies and one of its service-style replies as options (A)/(B),
and the positive and negative texts differ only in the final answer letter.
Both orders are used, so the direction is "choose the plain reply", not "A".

No weights change and no external text is used. llama.cpp's
cvector-generator turns the pairs into a control vector; llama-server applies
it with --control-vector-scaled. Measurement first: tools/codex_eval_pipeline.py
steer01 extracts, sweeps the strength and reads the result as predeclared.
"""
from __future__ import annotations

import random
import re
import struct
from pathlib import Path

_TEMPLATE = ("<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n{answer}")
_QUESTION = ("对方说：“{user}”\n下面两句回复，哪一句更像你平时说话的样子？\n(A) {a}\n(B) {b}\n只回答 A 或 B。")
_LOOP = re.compile(r"(.{2,8}?)\1{3,}", re.S)


def garbled(text: str) -> bool:
    """A reply that fell apart: a replacement character or a short run repeated four times or more."""
    return "�" in text or bool(_LOOP.search(text))


def _escape(text: str) -> str:
    # cvector-generator reads one prompt per line and processes escapes.
    return text.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n")


def _service(h: dict) -> bool:
    return h["hands_back"] or h["closing_offer"] or h["service"]


def harvest_pairs(cp, probe: dict, per_turn: int = 3) -> list[dict]:
    """(user, clean, service) triples from one probe's samples, same context each.

    Clean: not empty, no hard hint, no fabrication shape, no service marker.
    Service: a service marker (hand-back, closing offer, service phrase) and
    otherwise clean, so the contrast is service style and nothing else.
    """
    pairs = []
    for turn in probe["turns"]:
        if turn.get("mode") == "creative":
            continue
        system = cp._system(turn["messages"])
        clean, service = [], []
        for sample in turn["samples"]:
            text = (sample.get("text") or "").strip()
            if sample.get("error") or not text:
                continue
            h = cp.hints(text, user_text=turn.get("input") or "", system_text=system)
            if h["hard"] or h["fab_any"] or garbled(text):
                continue
            (service if _service(h) else clean).append(text)
        for index in range(min(per_turn, len(clean), len(service))):
            pairs.append({"key": turn["key"], "user": turn.get("input") or "",
                          "clean": clean[index], "service": service[index]})
    return pairs


def caa_lines(pairs: list[dict], seed: int = 20260928) -> tuple[list[str], list[str]]:
    """Positive (choose the clean reply) and negative lines, each pair in both orders."""
    rng = random.Random(seed)
    positive, negative = [], []
    for pair in pairs:
        for clean_first in rng.sample((True, False), 2):
            a, b = (pair["clean"], pair["service"]) if clean_first else (pair["service"], pair["clean"])
            question = _QUESTION.format(user=pair["user"], a=a, b=b)
            clean_letter, service_letter = ("A", "B") if clean_first else ("B", "A")
            positive.append(_escape(_TEMPLATE.format(question=question, answer=clean_letter)))
            negative.append(_escape(_TEMPLATE.format(question=question, answer=service_letter)))
    return positive, negative


_GGUF_TYPES = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def gguf_block_count(path: str | Path) -> int | None:
    """The model's layer count, from the GGUF metadata (``<arch>.block_count``)."""
    with open(path, "rb") as stream:
        if stream.read(4) != b"GGUF":
            return None
        version, = struct.unpack("<I", stream.read(4))
        if version < 2:
            return None
        _, kv_count = struct.unpack("<QQ", stream.read(16))

        def string():
            length, = struct.unpack("<Q", stream.read(8))
            return stream.read(length).decode("utf-8", "replace")

        def skip(kind):
            if kind == 8:
                string()
            elif kind == 9:
                inner, count = struct.unpack("<IQ", stream.read(12))
                for _ in range(count):
                    skip(inner)
            else:
                stream.read(struct.calcsize(_GGUF_TYPES[kind]))

        for _ in range(kv_count):
            key = string()
            kind, = struct.unpack("<I", stream.read(4))
            if key.endswith(".block_count") and kind in _GGUF_TYPES and kind not in (6, 7, 12):
                value, = struct.unpack(_GGUF_TYPES[kind], stream.read(struct.calcsize(_GGUF_TYPES[kind])))
                return int(value)
            skip(kind)
    return None


def layer_range(block_count: int | None) -> tuple[int, int]:
    """Middle-to-late layers (about 35–80% of depth), where style is reported to live."""
    n = block_count or 36
    return max(1, round(0.35 * n)), max(2, round(0.8 * n))
