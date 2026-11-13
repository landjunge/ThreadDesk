"""Synthetic token boundaries; no saved user content is read or rewritten."""

import json
import re

import pytest

from threaddesk.core.errors import SecretRejected
from threaddesk.core.secrets import reject_secrets

KEY = "sk-" + "A" * 24
LEGACY_SK_SHAPE = re.compile(r"sk-[A-Za-z0-9]{16,}", re.IGNORECASE)


def serialized(value, ensure_ascii):
    return json.dumps(
        {"text": value, "context": "Überblick 🧪"}, ensure_ascii=ensure_ascii
    )


def rejected_in_text_and_json(value):
    for text in (value, serialized(value, False), serialized(value, True)):
        with pytest.raises(SecretRejected) as caught:
            reject_secrets(text)
        assert value not in str(caught.value)


@pytest.mark.parametrize(
    "name",
    [
        "ThreadDesk-" + "a" * 32,
        "/Applications/ThreadDesk-" + "b" * 32 + ".app",
        "ThreadDeSK-" + "c" * 32,
    ],
    ids=["application-name", "application-path", "case-insensitive-name"],
)
def test_application_identifier_suffix_is_not_a_standalone_token(name):
    assert LEGACY_SK_SHAPE.search(name)  # The former false positive.
    for text in (name, serialized(name, False), serialized(name, True)):
        assert reject_secrets(text) is text  # Preserve the value, never sanitize it.


@pytest.mark.parametrize(
    "delimiter",
    [
        "",
        " ",
        "\n",
        "\t",
        '"',
        "'",
        "=",
        ":",
        "/",
        "-",
        "_",
        "(",
        "[",
        "{",
        "`",
        ",",
        ";",
    ],
    ids=[
        "start",
        "space",
        "newline",
        "tab",
        "double-quote",
        "single-quote",
        "equals",
        "colon",
        "slash",
        "hyphen",
        "underscore",
        "parenthesis",
        "bracket",
        "brace",
        "backtick",
        "comma",
        "semicolon",
    ],
)
def test_real_token_after_each_existing_delimiter_stays_blocked(delimiter):
    value = delimiter + KEY
    assert LEGACY_SK_SHAPE.search(value)
    rejected_in_text_and_json(value)


def test_json_escaped_control_delimiters_cannot_hide_a_token():
    # Includes newline, tab, CR, backspace/form-feed and all other JSON controls.
    for number in range(32):
        value = chr(number) + KEY
        assert LEGACY_SK_SHAPE.search(value)
        rejected_in_text_and_json(value)


@pytest.mark.parametrize("delimiter", ["\u2003", "\u00a0", "—", "😀"])
def test_unicode_delimiters_stay_blocked_when_json_uses_ascii_escapes(delimiter):
    value = delimiter + KEY
    for ensure_ascii in (False, True):
        text = serialized(value, ensure_ascii)
        assert LEGACY_SK_SHAPE.search(text)
        with pytest.raises(SecretRejected):
            reject_secrets(text)


@pytest.mark.parametrize(
    "escape", [r"\n", r"\r", r"\t", r"\b", r"\f", r"\u2003", r"\u0000", r"\ud83d\ude00"]
)
def test_literal_json_escape_sequences_are_conservatively_blocked(escape):
    rejected_in_text_and_json(escape + KEY)


@pytest.mark.parametrize(
    "value",
    [
        "ghp_" + "A" * 24,
        "gho_" + "B" * 24,
        "ghu_" + "C" * 24,
        "ghs_" + "D" * 24,
        "ghr_" + "E" * 24,
        "glpat-" + "A" * 24,
        "AKIA" + "A" * 16,
        "ntn_" + "A" * 24,
        "secret_" + "A" * 24,
        "xoxb-" + "A" * 24,
        "xoxa-" + "A" * 24,
        "xoxp-" + "A" * 24,
        "xoxr-" + "A" * 24,
        "xoxs-" + "A" * 24,
        "Bearer " + "A" * 16,
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "-----BEGIN EC PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
    ],
    ids=[
        "github-p",
        "github-o",
        "github-u",
        "github-s",
        "github-r",
        "gitlab",
        "aws",
        "notion-ntn",
        "notion-secret",
        "slack-b",
        "slack-a",
        "slack-p",
        "slack-r",
        "slack-s",
        "bearer",
        "pem",
        "pem-rsa",
        "pem-ec",
        "pem-openssh",
    ],
)
def test_other_provider_and_private_key_guards_remain_effective(value):
    rejected_in_text_and_json(value)


@pytest.mark.parametrize(
    "value",
    [
        "api_key=" + KEY,
        "API-KEY: " + KEY,
        "password=synthetic-placeholder",
        "secret: synthetic-placeholder",
        "token=synthetic-placeholder",
        "bearer: synthetic-placeholder",
        "api_key=prefix" + KEY,
    ],
    ids=[
        "api-key",
        "api-key-colon",
        "password",
        "secret",
        "token",
        "bearer",
        "embedded-labelled-value",
    ],
)
def test_credential_assignments_remain_blocked_independently_of_token_boundaries(value):
    rejected_in_text_and_json(value)


def test_alphanumeric_embedded_substrings_are_a_documented_detection_boundary():
    # The heuristic distinguishes a token start from an identifier substring.
    # It cannot classify an unlabelled key concatenated into such a word.
    for prefix in ("identifier", "7"):
        value = prefix + KEY
        assert LEGACY_SK_SHAPE.search(value)
        for text in (value, serialized(value, False), serialized(value, True)):
            assert reject_secrets(text) is text
        rejected_in_text_and_json("api_key=" + value)
