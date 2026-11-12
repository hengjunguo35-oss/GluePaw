"""敏感内容识别。

分级结果：
- DROP   完全不记录（私钥、云厂商密钥等，一旦泄露几乎不可挽回）
- MASK   进入隐私模式的临时保留（密码、验证码、卡号等）
- RECORD 普通历史

判定顺序：
1. 剪贴板自带的「别记录」标记（密码管理器写入），在 app.py 里先判断；
2. 本文件的 classify() 按风险从高到低匹配正则，命中即返回。
   卡号会再做 Luhn 校验、身份证号做校验位校验，避免把普通数字误判成敏感。
"""
from __future__ import annotations

import re
from typing import Iterable

DROP = "drop"
MASK = "mask"
RECORD = "record"

_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"), DROP),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), DROP),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), DROP),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"), DROP),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), DROP),
    ("jwt", re.compile(r"\beyJ[\w\-]{8,}\.[\w\-]{8,}\.[\w\-]{8,}\b"), MASK),
    ("cn_id", re.compile(r"\b\d{17}[\dXx]\b"), MASK),
    ("bank_card", re.compile(r"\b(?:\d[ -]?){11,18}\d\b"), MASK),
    ("otp", re.compile(r"^\d{6,8}$"), MASK),
    (
        "secret_assign",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b"
            r"\s*[:=]\s*\S{4,}"
        ),
        MASK,
    ),
]

# 剪贴板里由密码管理器写入的"别记录"标记
PRIVATE_FORMAT_NAMES = (
    'application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"',
    'application/x-qt-windows-mime;value="Clipboard Viewer Ignore"',
    "org.nspasteboard.ConcealedType",
    "x-kde-passwordManagerHint",
)


def _luhn(number: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", number)]
    if not 12 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _cn_id_ok(value: str) -> bool:
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    check = "10X98765432"
    if len(value) != 18:
        return False
    try:
        total = sum(int(value[i]) * weights[i] for i in range(17))
    except ValueError:
        return False
    return check[total % 11] == value[17].upper()


def classify(text: str) -> str:
    if not text:
        return RECORD
    for name, pattern, action in _RULES:
        match = pattern.search(text)
        if not match:
            continue
        if name == "bank_card" and not _luhn(match.group()):
            continue
        if name == "cn_id" and not _cn_id_ok(match.group()):
            continue
        return action
    return RECORD


def is_private_marked(formats: Iterable[str]) -> bool:
    lowered = [f.lower() for f in formats]
    for name in PRIVATE_FORMAT_NAMES:
        if name.lower() in lowered:
            return True
    for fmt in lowered:
        if "excludeclipboardcontentfrommonitorprocessing" in fmt:
            return True
        if "clipboard viewer ignore" in fmt:
            return True
    return False
