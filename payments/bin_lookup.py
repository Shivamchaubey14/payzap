import logging

logger = logging.getLogger(__name__)

# BIN database — first 6 digits of card → card info
# In production this would be a real BIN database API call
BIN_DATABASE = {
    '411111': {'bank': 'HDFC Bank', 'network': 'visa', 'type': 'credit', 'country': 'IN'},
    '400000': {'bank': 'ICICI Bank', 'network': 'visa', 'type': 'debit', 'country': 'IN'},
    '510510': {'bank': 'SBI', 'network': 'mastercard', 'type': 'credit', 'country': 'IN'},
    '607080': {'bank': 'Axis Bank', 'network': 'rupay', 'type': 'debit', 'country': 'IN'},
    '652100': {'bank': 'PNB', 'network': 'rupay', 'type': 'credit', 'country': 'IN'},
}

# Sanctioned country BINs — auto decline
SANCTIONED_BINS = {'999999', '888888'}


def lookup_bin(card_number: str) -> dict:
    """
    Look up card BIN (first 6 digits).
    Returns card network, bank, type and country.
    """
    card_number = card_number.replace(' ', '').replace('-', '')
    if len(card_number) < 6:
        return _unknown_bin()

    bin6 = card_number[:6]

    # Check sanctioned BINs first
    if bin6 in SANCTIONED_BINS:
        return {
            'bin': bin6,
            'bank': 'Unknown',
            'network': 'unknown',
            'type': 'unknown',
            'country': 'XX',
            'is_sanctioned': True,
        }

    info = BIN_DATABASE.get(bin6)
    if info:
        return {**info, 'bin': bin6, 'is_sanctioned': False}

    # Fallback — detect network from card number pattern
    return _detect_from_number(card_number)


def _detect_from_number(card_number: str) -> dict:
    """Detect card network from card number patterns."""
    network = 'unknown'

    if card_number.startswith('4'):
        network = 'visa'
    elif card_number[:2] in [str(i) for i in range(51, 56)]:
        network = 'mastercard'
    elif card_number[:4] in ('6521', '6522', '6070', '6071'):
        network = 'rupay'
    elif card_number[:2] in ('34', '37'):
        network = 'amex'

    return {
        'bin': card_number[:6],
        'bank': 'Unknown Bank',
        'network': network,
        'type': 'unknown',
        'country': 'IN',
        'is_sanctioned': False,
    }


def _unknown_bin() -> dict:
    return {
        'bin': '',
        'bank': 'Unknown',
        'network': 'unknown',
        'type': 'unknown',
        'country': 'IN',
        'is_sanctioned': False,
    }


def get_gateway_for_network(network: str) -> str:
    """
    Card network routing:
    Visa/Mastercard → razorpay (gateway A)
    RuPay → mock (gateway B — NPCI)
    """
    routing = {
        'visa': 'razorpay',
        'mastercard': 'razorpay',
        'rupay': 'mock',        # RuPay goes through NPCI
        'amex': 'razorpay',
        'unknown': 'mock',
    }
    return routing.get(network, 'mock')
