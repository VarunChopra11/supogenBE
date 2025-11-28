from fastapi import APIRouter, Depends, HTTPException
from api.v1.services.auth_services.auth import AuthService
from api.v1.services.discord_services.discord import get_user_servers, update_selected_forums
from api.v1.schemas.discord_servers import UpdateSelectedForumsRequest
from api.v1.utils.csrf import csrf_verification


router = APIRouter()
auth_service = AuthService()

@router.get("/get_servers")
async def get_servers(user=Depends(auth_service.get_current_user)):
	"""
	Returns the list of Discord servers the user has authorized.
	"""
	servers = await get_user_servers(user["user_id"])
	return {"servers": servers}


@router.put("/update_selected_forums")
async def update_forums(
    request: UpdateSelectedForumsRequest,
    user=Depends(auth_service.get_current_user),
    _=Depends(csrf_verification.verify_csrf)
):
	"""
	Update the selected_forums list for a specific Discord server.
	"""
	selected_forums_list = [forum.model_dump() for forum in request.selected_forums]
	
	success = await update_selected_forums(
		user_id=user["user_id"],
		server_id=request.server_id,
		selected_forums=selected_forums_list
	)
	
	if not success:
		raise HTTPException(status_code=404, detail="Server not found or update failed")
	
	return {"message": "Selected forums updated successfully"}
