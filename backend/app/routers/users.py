"""
User management endpoints for Clerk authentication integration.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import ClerkUser, get_clerk_user
from app.db.session import get_db
from app.db.models import UserRow

router = APIRouter(prefix="/users", tags=["users"])


class UserResponse(BaseModel):
    """User data returned to frontend."""

    patient_id: str  # Internal patient ID (UUID)
    clerk_user_id: str
    email: str
    first_name: str | None
    last_name: str | None


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    clerk_user: ClerkUser = Depends(get_clerk_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Get or create user mapping for authenticated Clerk user.

    This endpoint:
    1. Validates the Clerk JWT token
    2. Looks up the user in the database by clerk_user_id
    3. If not found, creates a new user record with a new patient_id
    4. Returns the patient_id for use in other API calls

    The patient_id is the internal UUID used throughout the app.
    The clerk_user_id is the external Clerk user identifier.
    """
    # Look up existing user
    user_row = db.query(UserRow).filter(UserRow.clerk_user_id == clerk_user.user_id).first()

    # Create new user if doesn't exist
    if not user_row:
        user_row = UserRow(
            clerk_user_id=clerk_user.user_id,
            email=clerk_user.email or "",
            first_name=clerk_user.first_name,
            last_name=clerk_user.last_name,
        )
        db.add(user_row)
        db.commit()
        db.refresh(user_row)

    return UserResponse(
        patient_id=user_row.id,  # This is the UUID patient_id used throughout the app
        clerk_user_id=user_row.clerk_user_id,
        email=user_row.email,
        first_name=user_row.first_name,
        last_name=user_row.last_name,
    )


@router.get("/by-clerk-id/{clerk_user_id}", response_model=UserResponse)
async def get_user_by_clerk_id(
    clerk_user_id: str,
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Get user by Clerk user ID (admin endpoint - no auth required for MVP).

    For production: Add admin authentication.
    """
    user_row = db.query(UserRow).filter(UserRow.clerk_user_id == clerk_user_id).first()

    if not user_row:
        raise HTTPException(status_code=404, detail=f"User not found: {clerk_user_id}")

    return UserResponse(
        patient_id=user_row.id,
        clerk_user_id=user_row.clerk_user_id,
        email=user_row.email,
        first_name=user_row.first_name,
        last_name=user_row.last_name,
    )
