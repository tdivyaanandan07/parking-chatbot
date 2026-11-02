import re
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()

# types of private data we never want to show
SENSITIVE = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "US_SSN"]

# phrases that look like prompt-injection or data-theft attempts
BLOCKED_PATTERNS = [
    r"ignore (all |your )?(previous|prior) instructions",
    r"system prompt",
    r"show (me )?(all )?(customers|users|reservations|bookings)",
    r"reveal .*(password|api key|secret)",
]


def redact(text: str) -> str:
    """Replace emails, phone numbers, card numbers etc. with placeholders."""
    results = _analyzer.analyze(text=text, language="en", entities=SENSITIVE)
    return _anonymizer.anonymize(text=text, analyzer_results=results).text


def is_malicious(text: str) -> bool:
    """True if the message looks like an attack."""
    t = text.lower()
    return any(re.search(p, t) for p in BLOCKED_PATTERNS)