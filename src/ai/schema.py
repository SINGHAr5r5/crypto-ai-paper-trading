"""Validates the AI decision JSON against spec §6.3."""

VALID_ACTIONS = {"BUY", "SELL", "CLOSE", "HOLD"}
VALID_DIRECTIONS = {"UP", "DOWN", "HOLD"}
VALID_RISK_LEVELS = {"low", "medium", "high"}

REQUIRED_FIELDS = [
    "symbol", "action", "direction", "confidence", "reasoning",
]


class InvalidDecision(ValueError):
    pass


def validate_decision(d: dict) -> dict:
    for field in REQUIRED_FIELDS:
        if field not in d:
            raise InvalidDecision(f"missing field: {field}")

    if d["action"] not in VALID_ACTIONS:
        raise InvalidDecision(f"invalid action: {d['action']}")
    if d["direction"] not in VALID_DIRECTIONS:
        raise InvalidDecision(f"invalid direction: {d['direction']}")

    try:
        confidence = float(d["confidence"])
    except (TypeError, ValueError):
        raise InvalidDecision(f"invalid confidence: {d.get('confidence')}")
    if not (0 <= confidence <= 1):
        raise InvalidDecision(f"confidence out of range: {confidence}")
    d["confidence"] = confidence

    for numeric_field in ("entry_price", "stop_loss", "take_profit", "position_size_pct"):
        if d.get(numeric_field) is not None:
            try:
                d[numeric_field] = float(d[numeric_field])
            except (TypeError, ValueError):
                raise InvalidDecision(f"invalid {numeric_field}: {d.get(numeric_field)}")

    if d.get("risk_level") is not None and d["risk_level"] not in VALID_RISK_LEVELS:
        raise InvalidDecision(f"invalid risk_level: {d['risk_level']}")

    return d
