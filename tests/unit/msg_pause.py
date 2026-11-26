"""A picklable pause. The msg limit test runs it in a child process."""

import time


def pause(_content: bytes) -> str:
    time.sleep(30)
    return ""


def ready(_content: bytes) -> str:
    return "ready"


def wide(_content: bytes) -> str:
    return "あ" * 200_000
