import re


def validate_vpa(vpa: str) -> bool:
    """
    Validate UPI VPA format: localpart@handle
    Examples: user@upi, merchant@hdfc, 9876543210@paytm
    """
    if not vpa or '@' not in vpa:
        return False
    pattern = r'^[a-zA-Z0-9._-]{3,}@[a-zA-Z]{3,}$'
    return bool(re.match(pattern, vpa.strip().lower()))


def normalize_vpa(vpa: str) -> str:
    return vpa.strip().lower()


def generate_upi_intent_url(vpa: str, amount: int, merchant_name: str,
                             transaction_ref: str, currency: str = 'INR') -> str:
    """
    Generate UPI Intent deep link.
    Format: upi://pay?pa=VPA&pn=NAME&am=AMOUNT&cu=CURRENCY&tr=REF
    """
    amount_rupees = amount / 100  # convert paise to rupees
    return (
        f"upi://pay"
        f"?pa={normalize_vpa(vpa)}"
        f"&pn={merchant_name.replace(' ', '%20')}"
        f"&am={amount_rupees:.2f}"
        f"&cu={currency}"
        f"&tr={transaction_ref}"
    )