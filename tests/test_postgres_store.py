from all_tomorrow.storage import hash_resume_token


def test_resume_tokens_are_stored_as_hashes() -> None:
    token = "resume_secret-value"
    digest = hash_resume_token(token)
    assert digest != token
    assert len(digest) == 64
    assert digest == hash_resume_token(token)

