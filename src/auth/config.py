"""
Authentication configuration.

Centralizes Supabase Auth and JWT settings.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Supabase Configuration
# =============================================================================

# Supabase project URL (e.g., https://xxx.supabase.co)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")

# Supabase anonymous/public key (safe to expose in frontend)
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# Supabase service role key (keep secret, for admin operations)
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# JWT secret for verifying Supabase tokens (same as JWT_SECRET in Supabase dashboard)
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

# =============================================================================
# OAuth Configuration
# =============================================================================

# Frontend URL for OAuth redirects
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

# OAuth callback path
OAUTH_CALLBACK_PATH = "/auth/callback"

# =============================================================================
# Token Configuration
# =============================================================================

# Access token expiry (in seconds) - Supabase default is 3600 (1 hour)
ACCESS_TOKEN_EXPIRY = int(os.environ.get("ACCESS_TOKEN_EXPIRY", "3600"))

# Refresh token expiry (in days) - Supabase default is 7 days
REFRESH_TOKEN_EXPIRY_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRY_DAYS", "7"))
