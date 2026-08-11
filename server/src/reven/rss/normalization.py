"""Normalization rules shared by RSS keyword validation and persistence."""

import unicodedata


def normalize_keyword(term: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", term).casefold().split())
