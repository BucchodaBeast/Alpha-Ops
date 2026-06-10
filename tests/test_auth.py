"""
tests/test_auth.py
Unit tests for auth.py — JWT creation/validation, user registration,
password hashing, watchlist management.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from unittest.mock import MagicMock, patch
import uuid


@pytest.fixture
def auth(tmp_path):
    db_file = str(tmp_path / 'auth_test.db')
    with patch.dict(os.environ, {
        'DATABASE_PATH': db_file,
        'SUPABASE_URL': '', 'SUPABASE_KEY': '',
        'JWT_SECRET': 'test-secret-key-for-testing-only'
    }):
        import importlib
        import database as db_module
        importlib.reload(db_module)
        import auth as auth_module
        importlib.reload(auth_module)
        yield auth_module


class TestPasswordHashing:
    def test_hash_password_not_plaintext(self, auth):
        h = auth.hash_password('mysecret')
        assert h != 'mysecret'

    def test_verify_correct_password(self, auth):
        h = auth.hash_password('mysecret')
        assert auth.verify_password('mysecret', h) is True

    def test_verify_wrong_password(self, auth):
        h = auth.hash_password('mysecret')
        assert auth.verify_password('wrongpassword', h) is False

    def test_same_password_different_hash(self, auth):
        # bcrypt salts should make hashes different
        h1 = auth.hash_password('same')
        h2 = auth.hash_password('same')
        assert h1 != h2

    def test_empty_password_hashes(self, auth):
        h = auth.hash_password('')
        assert h != ''


class TestJWT:
    def test_create_and_decode_token(self, auth):
        token = auth.create_token('user-123', 'test@example.com')
        payload = auth.decode_token(token)
        assert payload['sub'] == 'user-123'
        assert payload['email'] == 'test@example.com'

    def test_expired_token_raises(self, auth):
        import time
        token = auth.create_token('user-123', 'x@x.com', expires_in_seconds=1)
        time.sleep(2)
        with pytest.raises(auth.TokenExpiredError):
            auth.decode_token(token)

    def test_tampered_token_raises(self, auth):
        token = auth.create_token('user-123', 'x@x.com')
        tampered = token[:-5] + 'XXXXX'
        with pytest.raises(auth.InvalidTokenError):
            auth.decode_token(tampered)

    def test_token_contains_no_password(self, auth):
        token = auth.create_token('user-123', 'x@x.com')
        assert 'password' not in token


class TestUserRegistration:
    def test_register_new_user(self, auth):
        user = auth.register_user('alice@example.com', 'SecurePass123!')
        assert user['email'] == 'alice@example.com'
        assert 'id' in user
        assert 'password_hash' not in user  # never expose hash

    def test_duplicate_email_raises(self, auth):
        auth.register_user('bob@example.com', 'Pass123!')
        with pytest.raises(auth.UserExistsError):
            auth.register_user('bob@example.com', 'DifferentPass!')

    def test_login_correct_credentials(self, auth):
        auth.register_user('carol@example.com', 'MyPass99!')
        result = auth.login('carol@example.com', 'MyPass99!')
        assert 'token' in result
        assert result['user']['email'] == 'carol@example.com'

    def test_login_wrong_password_raises(self, auth):
        auth.register_user('dave@example.com', 'RightPass1!')
        with pytest.raises(auth.InvalidCredentialsError):
            auth.login('dave@example.com', 'WrongPass!')

    def test_login_unknown_email_raises(self, auth):
        with pytest.raises(auth.InvalidCredentialsError):
            auth.login('nobody@example.com', 'whatever')

    def test_registered_user_not_admin_by_default(self, auth):
        user = auth.register_user('eve@example.com', 'Pass123!')
        assert user.get('is_admin') is False


class TestWatchlists:
    @pytest.fixture
    def user(self, auth):
        return auth.register_user('watcher@example.com', 'Watch123!')

    def test_add_country_watchlist(self, auth, user):
        auth.update_watchlist(user['id'], countries=['Nigeria', 'Kenya'])
        wl = auth.get_watchlist(user['id'])
        assert 'Nigeria' in wl['countries']

    def test_add_sector_watchlist(self, auth, user):
        auth.update_watchlist(user['id'], sectors=['Oil & Gas', 'Garment Manufacturing'])
        wl = auth.get_watchlist(user['id'])
        assert 'Oil & Gas' in wl['sectors']

    def test_update_overwrites_previous(self, auth, user):
        auth.update_watchlist(user['id'], countries=['Nigeria'])
        auth.update_watchlist(user['id'], countries=['Kenya'])
        wl = auth.get_watchlist(user['id'])
        assert 'Nigeria' not in wl['countries']
        assert 'Kenya' in wl['countries']

    def test_empty_watchlist_by_default(self, auth, user):
        wl = auth.get_watchlist(user['id'])
        assert wl['countries'] == []
        assert wl['sectors'] == []

    def test_unknown_user_returns_empty_watchlist(self, auth):
        wl = auth.get_watchlist('nonexistent-user-id')
        assert wl == {'countries': [], 'sectors': [], 'analysts': []}
