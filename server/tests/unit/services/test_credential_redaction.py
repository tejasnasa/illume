"""Git output that echoes a tokenised clone URL is masked before anything can repeat it.

When GitHub rejects the token, git prints the URL with the token in it (``could not
read Password for 'https://<token>@github.com'``). That text becomes the exception
message, which the ingest task logs and publishes to the browser and the sync task
stores as its error.
"""

import git
import pytest

from app.services.repo_cache import redact_credentials, redact_git_error

pytestmark = pytest.mark.unit

TOKEN = "ghs_0123456789abcdef"


def test_a_token_only_url_is_masked():
    text = f"fatal: could not read Password for 'https://{TOKEN}@github.com': prompts disabled"

    assert redact_credentials(text) == (
        "fatal: could not read Password for 'https://*****@github.com': prompts disabled"
    )


def test_user_and_password_and_every_url_in_the_text_are_masked():
    text = f"https://x-access-token:{TOKEN}@github.com/o/r.git then http://u:p@host/x"

    assert redact_credentials(text) == "https://*****@github.com/o/r.git then http://*****@host/x"


def test_a_url_without_credentials_is_left_alone():
    assert redact_credentials("https://github.com/o/r and me@example.com") == (
        "https://github.com/o/r and me@example.com"
    )


@pytest.mark.parametrize("empty", ["", None])
def test_empty_output_passes_through(empty):
    assert redact_credentials(empty) == empty


def test_a_git_error_carries_no_token_after_redaction():
    exc = git.GitCommandError(
        ["git", "fetch", f"https://{TOKEN}@github.com/o/r"],
        128,
        stderr=f"fatal: could not read Password for 'https://{TOKEN}@github.com'",
        stdout=f"remote: https://{TOKEN}@github.com/o/r",
    )

    assert redact_git_error(exc) is exc
    assert TOKEN not in str(exc)
    assert TOKEN not in repr(exc)
