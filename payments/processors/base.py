from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PaymentResult:
    """Standardized result returned by every gateway."""
    success: bool
    status: str                          # authorized / captured / failed
    gateway_txn_id: str = ''
    error_code: str = ''
    error_message: str = ''
    raw_response: dict = None

    def __post_init__(self):
        if self.raw_response is None:
            self.raw_response = {}


class PaymentProcessor(ABC):
    """
    Abstract base class for all payment gateways.
    Every gateway (Mock, Razorpay, Stripe, UPI) must implement these methods.
    """

    @abstractmethod
    def authorize(self, payment, payment_data: dict) -> PaymentResult:
        """
        Place a hold on the customer's funds without capturing.
        Used in two-step authorize + capture flow.
        """
        pass

    @abstractmethod
    def capture(self, payment, amount: int) -> PaymentResult:
        """
        Capture previously authorized funds.
        amount is in paise.
        """
        pass

    @abstractmethod
    def refund(self, payment, amount: int) -> PaymentResult:
        """
        Refund a captured payment.
        amount is in paise — can be partial.
        """
        pass

    @abstractmethod
    def check_status(self, gateway_txn_id: str) -> PaymentResult:
        """
        Poll the gateway for current payment status.
        Used for async methods like UPI and net banking.
        """
        pass
