from app.security import hash_password, verify_password


class TestPasswordHashing:
    def test_correct_password_verifies(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-horse-battery-staple")
        assert not verify_password("wrong-password", hashed)

    def test_hash_is_not_the_plaintext(self):
        hashed = hash_password("hunter2")
        assert hashed != "hunter2"


class TestArgon2id:
    def test_new_hashes_are_argon2id(self):
        assert hash_password("correct-horse-battery-staple").startswith("$argon2id$v=19$m=65536,t=3,p=4$")

    def test_same_password_gets_a_different_salt(self):
        assert hash_password("same password here") != hash_password("same password here")

    def test_legacy_bcrypt_still_verifies_and_needs_rehash(self):
        import bcrypt
        from app.security import needs_rehash
        legacy = bcrypt.hashpw(b"old-password-123", bcrypt.gensalt(12)).decode()
        assert verify_password("old-password-123", legacy)
        assert not verify_password("wrong", legacy)
        assert needs_rehash(legacy)
        assert not needs_rehash(hash_password("old-password-123"))

    def test_garbage_hash_is_a_failed_check_not_a_crash(self):
        assert not verify_password("anything", "not-a-hash")


class TestPasswordPolicy:
    def test_rules(self):
        import pytest
        from app.security import PasswordPolicyError, check_password_policy
        check_password_policy("twelve chars", "a@example.com")
        for bad in ("short", "x" * 129, "me a@example.com!!"):
            with pytest.raises(PasswordPolicyError):
                check_password_policy(bad, "A@example.com")
