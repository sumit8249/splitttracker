"""Small, testable helpers for parsing receipts and splitting costs."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")


def _money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).replace(",", "")).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount >= 0 else None


def normalize_receipt(receipt: Any) -> dict[str, Any] | None:
    """Validate and normalize the receipt object returned by Gemini."""
    if not isinstance(receipt, dict):
        return None

    normalized_items: list[dict[str, Any]] = []
    raw_items = receipt.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            amount = _money(item.get("amount"))
            if name and amount is not None:
                normalized_items.append({"name": name, "amount": amount})

    total = _money(receipt.get("total"))
    subtotal = _money(receipt.get("subtotal"))
    tax = _money(receipt.get("tax"))
    tip = _money(receipt.get("tip"))
    currency = str(receipt.get("currency") or "USD").strip().upper()[:3]
    return {
        "currency": currency or "USD",
        "items": normalized_items,
        "subtotal": subtotal,
        "tax": tax,
        "tip": tip,
        "total": total,
    }


def parse_assistant_response(raw: str) -> tuple[str, dict[str, Any] | None]:
    """Extract user-facing text and optional receipt data from Gemini JSON."""
    fallback = raw.strip() or "I couldn't read a response. Please try again."
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback, None
    if not isinstance(payload, dict):
        return fallback, None

    message = payload.get("message")
    text = str(message).strip() if message is not None else fallback
    return text or fallback, normalize_receipt(payload.get("receipt"))


def _attendees(names: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        cleaned = name.strip()
        folded = cleaned.casefold()
        if cleaned and folded not in seen:
            unique.append(cleaned)
            seen.add(folded)
    return unique


def _allocate(amount: Decimal, names: list[str], shares: dict[str, Decimal]) -> None:
    """Add a cent-accurate equal allocation to selected people."""
    cents = int((amount.quantize(CENT, rounding=ROUND_HALF_UP) / CENT).to_integral_value())
    base, remainder = divmod(cents, len(names))
    for index, name in enumerate(names):
        allocated_cents = base + (1 if index < remainder else 0)
        shares[name] += Decimal(allocated_cents) * CENT


def split_equally(total: Any, attendees: list[str]) -> dict[str, Decimal]:
    """Split a total evenly, assigning leftover cents in input order."""
    names = _attendees(attendees)
    amount = _money(total)
    if not names:
        raise ValueError("At least one attendee is required.")
    if amount is None:
        raise ValueError("The bill total must be a non-negative amount.")
    shares = {name: Decimal("0.00") for name in names}
    _allocate(amount, names, shares)
    return shares


def calculate_itemized_split(
    items: list[dict[str, Any]], attendees: list[str]
) -> dict[str, Decimal]:
    """Split each line equally among its listed participants (or everyone)."""
    names = _attendees(attendees)
    if not names:
        raise ValueError("At least one attendee is required.")

    canonical = {name.casefold(): name for name in names}
    shares = {name: Decimal("0.00") for name in names}
    for item in items:
        if not isinstance(item, dict):
            continue
        amount = _money(item.get("amount"))
        if amount is None or amount == 0:
            continue

        raw_participants = item.get("participants", "")
        if isinstance(raw_participants, list):
            requested = [str(person).strip() for person in raw_participants]
        else:
            requested = [person.strip() for person in str(raw_participants).split(",")]
        selected = list(dict.fromkeys(
            canonical[person.casefold()]
            for person in requested
            if person.casefold() in canonical
        ))
        _allocate(amount, selected or names, shares)
    return shares


def format_amount(amount: Any, currency: str = "USD") -> str:
    """Render a numeric amount with its currency code."""
    value = _money(amount)
    if value is None:
        value = Decimal("0.00")
    return f"{currency.upper()} {value:,.2f}"