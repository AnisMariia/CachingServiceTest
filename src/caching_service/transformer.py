"""Stand-in for the external service whose calls we want to minimise."""

import time

# Simulated network latency, so that the benefit of the cache is visible.
LATENCY_SECONDS = 0.05


def transform(text: str) -> str:
    time.sleep(LATENCY_SECONDS)
    return text.upper()
