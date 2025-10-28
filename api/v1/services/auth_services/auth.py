import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, status, Request
from jose import JWTError, ExpiredSignatureError

from api.v1.utils.jwt import create_jwt_token
from api.v1.config import auth_config
from api.v1.db.session import DatabaseSession
from api.v1.schemas.users import UserCreate, UserResponse

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self):
        self.clerk_jwks_url = auth_config.CLERK_JWKS_URL
        self.clerk_audience = auth_config.CLERK_AUDIENCE
        self.clerk_issuer = auth_config.CLERK_ISSUER
        self.JWT_TOKEN_EXPIRE_MINUTES = 10080  # 7 Days

    @staticmethod
    def generate_csrf_token(length: int = 32) -> str:
        """Generate a CSRF token to be returned to the client."""
        return secrets.token_urlsafe(length)

    @staticmethod
    def _extract_bearer_token(authorization: Optional[str]) -> str:
        """Extract the bearer token from the authorization header."""
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header"
            )
        return authorization.split(" ", 1)[1].strip()

    async def verify_clerk_jwt(self, token: str) -> Dict[str, Any]:
        """Verify the Clerk RS256 JWT using JWKS and return decoded claims."""
        try:
            jwks_client = PyJWKClient(self.clerk_jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.clerk_audience,
                issuer=self.clerk_issuer,
                options={
                    "require": ["exp", "iat"],
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
            return claims
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}"
            ) from e

    async def handshake_service(self, authorization: str) -> Dict[str, Any]:
        """
        Validate Clerk JWT and mint backend session.
        Returns user information and JWT token.
        """
        clerk_jwt = self._extract_bearer_token(authorization)
        claims = await self.verify_clerk_jwt(clerk_jwt)

        user_id = claims.get("user_id") or claims.get("sub")
        full_name = claims.get("full_name")
        email = claims.get("email")
        image_url = claims.get("image_url")

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing subject in token"
            )

        now = datetime.now(timezone.utc)
        try:
            user = UserCreate(
                email=email,
                user_id=user_id,
                name=full_name,
                picture=image_url,
                created_at=now,
                updated_at=now
            )
        except Exception as e:
            logger.error(f"User validation error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid user data format"
            ) from e

        db = DatabaseSession.get_db()
        try:
            await db["users"].update_one(
                {"email": user.email},
                {
                    "$set": user.model_dump(exclude={"created_at"}, by_alias=True),
                    "$setOnInsert": {"created_at": user.created_at}
                },
                upsert=True
            )
        except Exception as e:
            logger.error(f"Database error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save user information"
            ) from e

        session_payload = {
            "user_id": user_id,
            "full_name": full_name,
            "email": email,
            "image_url": image_url,
        }

        jwt_token = create_jwt_token(
            session_payload,
            expires_delta=timedelta(minutes=self.JWT_TOKEN_EXPIRE_MINUTES)
        )

        return {
            "user": session_payload,
            "token": jwt_token,
        }

    @staticmethod
    async def get_token_from_cookie(request: Request) -> str:
        """Extract JWT token from cookie."""
        token = request.cookies.get("access_token")
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token"
            )
        return token

    async def get_current_user(self, request: Request) -> Dict[str, Any]:
        """Get current user from JWT token in cookie."""
        db = DatabaseSession.get_db()
        if db is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection not available"
            )

        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials",
            headers={"WWW-Authenticate": "Bearer"}
        )

        try:
            token = await self.get_token_from_cookie(request)
            payload = jwt.decode(
                token, 
                auth_config.JWT_SECRET_KEY,
                algorithms=["HS256"]
            )
            user_id: str = payload.get("user_id")
            if user_id is None:
                raise credentials_exception
        except (ExpiredSignatureError, JWTError):
            raise credentials_exception

        user = await db["users"].find_one(
            {"user_id": user_id},
            {"_id": 0, "email": 1, "name": 1, "picture": 1}
        )

        if not user:
            raise credentials_exception

        return UserResponse(
            user_id=user_id,
            full_name=user.get("name"),
            email=user.get("email"),
            image_url=user.get("picture")
        )
