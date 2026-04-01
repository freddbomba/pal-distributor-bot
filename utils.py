import re
import base64


def validate_ton_address(address: str) -> bool:
    """Validate a TON address format (raw or user-friendly).

    User-friendly addresses start with EQ or UQ (base64, 48 chars)
    or use the raw hex format (64 hex chars with colon separator).
    """
    address = address.strip()

    # User-friendly format: EQ... or UQ... (base64url, 48 chars)
    if re.match(r"^[EU]Q[A-Za-z0-9_-]{46}$", address):
        try:
            # Verify it's valid base64url
            padded = address + "=" * (4 - len(address) % 4) if len(address) % 4 else address
            base64.urlsafe_b64decode(padded)
            return True
        except Exception:
            return False

    # Raw format: workchain:hex (e.g., 0:abc...def)
    if re.match(r"^-?\d+:[0-9a-fA-F]{64}$", address):
        return True

    return False


def format_pal_amount(amount: float) -> str:
    """Format PAL amount for display, removing unnecessary decimals."""
    if amount == int(amount):
        return str(int(amount))
    return f"{amount:.2f}"


def format_status(status: str) -> str:
    """Translate proposal status to Italian display label."""
    labels = {
        "awaiting_endorsement": "In attesa di appoggio",
        "pending": "In attesa (countdown 24h)",
        "on_hold": "In sospeso",
        "approved": "Approvata",
        "rejected": "Rifiutata",
        "failed": "Fallita",
    }
    return labels.get(status, status)


def truncate(text: str, max_len: int = 100) -> str:
    """Truncate text to max_len characters with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
