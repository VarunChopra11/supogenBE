from datetime import timedelta

from fastapi import APIRouter, Depends

from api.v1.schemas.users import UserResponse
from api.v1.services.auth_services.auth import AuthService
from api.v1.utils.jwt import create_jwt_token
from api.v1.utils.crypto import fernet_encrypt


router = APIRouter(prefix="/auth/discord", tags=["auth", "discord"])

auth_service = AuthService()


@router.get("/token")
async def mint_discord_scoped_token(user=Depends(auth_service.get_current_user)):
	"""
	Secured endpoint that requires a valid backend JWT in cookies.
	It returns a new 5-minute JWT whose payload matches UserResponse.
	"""
	user_payload = UserResponse(
		user_id=user["user_id"],
		email=user["email"],
		name=user["name"],
		picture=user["picture"],
	).model_dump()

	jwt_token = create_jwt_token(user_payload, expires_delta=timedelta(minutes=5))
	encrypted_token = fernet_encrypt(jwt_token)
	return {"token": encrypted_token}
