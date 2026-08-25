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
