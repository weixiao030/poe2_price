"""Shared unique/tablet name labels and cleanup of previously generated forms."""
import re

PRICE_TEXT_RE = r"(?:<1|[0-9]+(?:\.[0-9]+)?)[CDE]"
UNIQUE_SUFFIX_PRICE_RE = rf"\[<<{PRICE_TEXT_RE}>>\]"


def strip_existing_price(name: str) -> str:
    markup = re.fullmatch(
        rf"\[[^\]\r\n|]*{PRICE_TEXT_RE}[^\]\r\n|]*\|([^\]\r\n]+)\]",
        name.strip(),
    )
    if markup:
        return markup.group(1).strip()
    if re.search(rf"\s*{UNIQUE_SUFFIX_PRICE_RE}$", name):
        return re.sub(rf"\s*{UNIQUE_SUFFIX_PRICE_RE}$", "", name).strip()
    if re.search(rf"<<\[{PRICE_TEXT_RE}\]>>$", name):
        return re.sub(rf"<<\[{PRICE_TEXT_RE}\]>>$", "", name).strip()
    if re.search(rf"\s*\[{PRICE_TEXT_RE}\]$", name):
        return re.sub(rf"\s*\[{PRICE_TEXT_RE}\]$", "", name).strip()
    if re.search(rf"={PRICE_TEXT_RE}$", name):
        return re.sub(rf"={PRICE_TEXT_RE}$", "", name).strip()
    return name


def format_unique_price_name(base_name: str, price: str, label_mode: str) -> str:
    if label_mode in {"suffix", "compat"}:
        return f"{base_name}[<<{price}>>]"
    if label_mode == "markup":
        return f"[{price}|{base_name}]"
    if label_mode == "newline":
        return f"{base_name}\n[{price}]"
    if label_mode == "overlay":
        return f"{base_name}<<[{price}]>>"
    return base_name
