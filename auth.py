"""
auth.py — Alpha Ops Authentication & Watchlist Management

Provides:
  - Password hashing (bcrypt)
  - JWT creation / validation
  - User registration / login
  - Per-user watchlists (countries, sectors, analysts)

All user data stored in SQLite (or Supabase via env vars).
"""

import os
import sqlite3
import uuid
import json
import logging
import hashlib
import hmac
import base64
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

DB_PATH = os.getenv('DATABASE_PATH', 'alphaops.db')
JWT_SECRET = os.getenv('JWT_SECRET', os.urandom(32).hex())
JWT_EXPIRE_SECONDS = int(os.getenv('JWT_EXPIRE_SECONDS', str(60 * 60 * 24 * 7)))  # 7 days

# ── Custom exceptions ─────────────────────────────────────────────────────────

class UserExistsError(Exception): pass
class InvalidCredentialsError(Exception): pass
class TokenExpiredError(Exception): pass
class InvalidTokenError(Exception): pass


# ── Database setup ────────────────────────────────────────────────────────────

@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_tables():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id           TEXT PRIMARY KEY,
                email        TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_admin     INTEGER DEFAULT 0,
                created_at   TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS watchlists (
                user_id      TEXT PRIMARY KEY,
                countries    TEXT DEFAULT '[]',
                sectors      TEXT DEFAULT '[]',
                analysts     TEXT DEFAULT '[]',
                updated_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
        conn.commit()


_ensure_tables()


# ── Password hashing (lightweight bcrypt-style using PBKDF2) ─────────────────
# Using hashlib PBKDF2 to avoid external bcrypt dep while still being secure.

_ITERATIONS = 260_000  # OWASP recommended minimum for PBKDF2-SHA256

def hash_password(password: str) -> str:
    """Hash password with PBKDF2-HMAC-SHA256 + random salt."""
    salt = os.urandom(32)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, _ITERATIONS)
    return base64.b64encode(salt + dk).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored PBKDF2 hash."""
    try:
        decoded = base64.b64decode(stored_hash.encode())
        salt = decoded[:32]
        stored_dk = decoded[32:]
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, _ITERATIONS)
        return hmac.compare_digest(dk, stored_dk)
    except Exception:
        return False


# ── JWT (minimal, no external deps) ──────────────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


def create_token(user_id: str, email: str, expires_in_seconds: int = None) -> str:
    """Create a signed JWT token."""
    expires_in = expires_in_seconds or JWT_EXPIRE_SECONDS
    header = _b64url_encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())
    payload = _b64url_encode(json.dumps({
        'sub': user_id,
        'email': email,
        'iat': int(time.time()),
        'exp': int(time.time()) + expires_in,
    }).encode())
    signing_input = f"{header}.{payload}"
    sig = hmac.new(
        JWT_SECRET.encode(),
        signing_input.encode(),
        hashlib.sha256
    ).digest()
    signature = _b64url_encode(sig)
    return f"{signing_input}.{signature}"


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises on invalid/expired."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise InvalidTokenError("Malformed token")

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}"

        expected_sig = _b64url_encode(
            hmac.new(JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(expected_sig, sig_b64):
            raise InvalidTokenError("Invalid token signature")

        payload = json.loads(_b64url_decode(payload_b64))

        if payload.get('exp', 0) < time.time():
            raise TokenExpiredError("Token has expired")

        return payload
    except (TokenExpiredError, InvalidTokenError):
        raise
    except Exception as e:
        raise InvalidTokenError(f"Token decode failed: {e}")


# ── User management ───────────────────────────────────────────────────────────

def register_user(email: str, password: str) -> dict:
    """Register a new user. Raises UserExistsError if email taken."""
    email = email.lower().strip()
    with _conn() as conn:
        existing = conn.execute(
            'SELECT id FROM users WHERE email=?', (email,)
        ).fetchone()
        if existing:
            raise UserExistsError(f"Email '{email}' is already registered")

        user_id = str(uuid.uuid4())
        password_hash = hash_password(password)
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            'INSERT INTO users (id, email, password_hash, is_admin, created_at) VALUES (?,?,?,0,?)',
            (user_id, email, password_hash, now)
        )
        # Create empty watchlist row
        conn.execute(
            'INSERT INTO watchlists (user_id) VALUES (?)', (user_id,)
        )

    return {
        'id': user_id,
        'email': email,
        'is_admin': False,
        'created_at': now,
    }


def login(email: str, password: str) -> dict:
    """Authenticate user. Returns {token, user} or raises InvalidCredentialsError."""
    email = email.lower().strip()
    with _conn() as conn:
        row = conn.execute(
            'SELECT id, email, password_hash, is_admin FROM users WHERE email=?', (email,)
        ).fetchone()

    if not row:
        raise InvalidCredentialsError("Invalid email or password")

    if not verify_password(password, row['password_hash']):
        raise InvalidCredentialsError("Invalid email or password")

    token = create_token(row['id'], row['email'])
    return {
        'token': token,
        'user': {
            'id': row['id'],
            'email': row['email'],
            'is_admin': bool(row['is_admin']),
        }
    }


def get_user_by_id(user_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            'SELECT id, email, is_admin, created_at FROM users WHERE id=?', (user_id,)
        ).fetchone()
    return dict(row) if row else None


# ── Watchlists ────────────────────────────────────────────────────────────────

_EMPTY_WL = {'countries': [], 'sectors': [], 'analysts': []}


def get_watchlist(user_id: str) -> dict:
    """Return user's watchlist. Returns empty defaults if not found."""
    try:
        with _conn() as conn:
            row = conn.execute(
                'SELECT countries, sectors, analysts FROM watchlists WHERE user_id=?', (user_id,)
            ).fetchone()
        if not row:
            return dict(_EMPTY_WL)
        return {
            'countries': _deser(row['countries']),
            'sectors':   _deser(row['sectors']),
            'analysts':  _deser(row['analysts']),
        }
    except Exception as e:
        logger.error(f"[AUTH] get_watchlist failed: {e}")
        return dict(_EMPTY_WL)


def update_watchlist(user_id: str,
                     countries: list = None,
                     sectors: list = None,
                     analysts: list = None) -> dict:
    """
    Update user watchlist fields. Only provided fields are updated.
    Returns the resulting watchlist.
    """
    current = get_watchlist(user_id)
    new_wl = {
        'countries': countries if countries is not None else current['countries'],
        'sectors':   sectors   if sectors   is not None else current['sectors'],
        'analysts':  analysts  if analysts  is not None else current['analysts'],
    }
    now = datetime.now(timezone.utc).isoformat()

    try:
        with _conn() as conn:
            # Ensure row exists
            conn.execute(
                'INSERT OR IGNORE INTO watchlists (user_id) VALUES (?)', (user_id,)
            )
            conn.execute('''
                UPDATE watchlists
                SET countries=?, sectors=?, analysts=?, updated_at=?
                WHERE user_id=?
            ''', (
                json.dumps(new_wl['countries']),
                json.dumps(new_wl['sectors']),
                json.dumps(new_wl['analysts']),
                now, user_id
            ))
    except Exception as e:
        logger.error(f"[AUTH] update_watchlist failed: {e}")

    return new_wl


# ── Flask middleware helpers ──────────────────────────────────────────────────

def require_auth(f):
    """Flask decorator: require valid JWT in Authorization: Bearer <token> header."""
    from functools import wraps
    from flask import request, jsonify

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing or invalid Authorization header'}), 401
        token = auth_header[7:]
        try:
            payload = decode_token(token)
            request.user_id = payload['sub']
            request.user_email = payload['email']
        except TokenExpiredError:
            return jsonify({'error': 'Token expired — please log in again'}), 401
        except InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)

    return decorated


def _deser(v):
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v:
        try:
            r = json.loads(v)
            return r if isinstance(r, list) else []
        except Exception:
            return []
    return []
