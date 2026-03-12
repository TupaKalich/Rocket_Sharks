BOOKING_STATUSES = [
    "new",
    "pending_confirmation",
    "confirmed",
    "rejected",
    "canceled",
]

ALLOWED_STATUS_TRANSITIONS = {
    "new": {"pending_confirmation", "canceled"},
    "pending_confirmation": {"confirmed", "rejected", "canceled"},
    "confirmed": set(),
    "rejected": set(),
    "canceled": set(),
}

PAYMENT_LINK_TYPES = ["personal", "tournament"]
CRYPTO_EXCHANGES = ["Bybit", "HTX"]
ALLOWED_UPLOAD_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
ALLOWED_UPLOAD_MIME = {"image/png", "image/jpeg", "application/pdf"}
IDEMPOTENCY_SESSION_KEY = "proof_form_token"
