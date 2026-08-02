"""
Authentication utilities for Clerk integration.
"""

from typing import Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel
import httpx


class ClerkUser(BaseModel):
    """Clerk user data from JWT validation."""

    user_id: str
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


async def get_clerk_user(request: Request) -> ClerkUser:
    """
    Extract and validate Clerk user from Authorization header.

    For MVP: This is a simplified version that trusts the frontend.
    For production: Validate JWT signature using Clerk's public keys.

    Args:
        request: FastAPI request object

    Returns:
        ClerkUser with validated user data

    Raises:
        HTTPException: If authentication fails
    """
    # Get Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    # Extract token
    token = auth_header.replace("Bearer ", "")

    # TODO: For production, validate JWT signature using Clerk's JWKS endpoint
    # For MVP, we'll trust the frontend and extract claims without validation

    try:
        # Simple base64 decode of JWT payload (NOT production-ready)
        import base64
        import json

        payload_encoded = token.split(".")[1]
        # Add padding if needed
        padding = 4 - (len(payload_encoded) % 4)
        if padding != 4:
            payload_encoded += "=" * padding

        payload_decoded = base64.urlsafe_b64decode(payload_encoded)
        claims = json.loads(payload_decoded)

        return ClerkUser(
            user_id=claims.get("sub", ""),
            email=claims.get("email"),
            first_name=claims.get("first_name"),
            last_name=claims.get("last_name"),
        )

    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc


async def validate_clerk_jwt_production(token: str) -> dict:
    """
    Production-grade JWT validation using Clerk's JWKS endpoint.

    SECURITY WARNING: This function is not yet implemented.
    Implement before deploying to production.

    Steps:
    1. Fetch Clerk's public keys from: https://api.clerk.com/v1/jwks
    2. Verify JWT signature using the appropriate key
    3. Validate expiration, issuer, and audience claims
    4. Return validated claims

    See: https://clerk.com/docs/backend-requests/handling/manual-jwt
    """
    # TODO: Implement production JWT validation
    # Use PyJWT library: jwt.decode(token, jwks, algorithms=["RS256"], audience="...")
    raise NotImplementedError("Production JWT validation not yet implemented")
