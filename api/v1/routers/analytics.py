from fastapi import APIRouter, Depends, HTTPException, status, Query
import logging

from api.v1.services.auth_services.auth import AuthService
from api.v1.services.analytics import analytics_service

router = APIRouter()
auth_service = AuthService()
logger = logging.getLogger(__name__)


@router.get("/discord/analytics")
async def get_discord_analytics(
    user=Depends(auth_service.get_current_user),
):
    """
    Get Discord chat analytics for the authenticated user.
    
    Returns:
        - Total resolved tickets (total and resolved count)
        - Average resolution time in hours
        - First contact resolution percentage
    """
    try:
        user_id = user["user_id"]
        analytics = await analytics_service.get_discord_analytics(user_id)
        
        return {"data": analytics}
        
    except Exception as e:
        logger.error(f"Error fetching Discord analytics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch analytics"
        )


@router.get("/discord/chats/resolved")
async def get_resolved_chats(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    user=Depends(auth_service.get_current_user),
):
    """
    Get paginated resolved Discord chats for the authenticated user.
    
    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Number of chats per page (default: 10, max: 100)
    
    Returns:
        - chats: List of resolved Discord chats
        - pagination: Pagination metadata
    """
    try:
        user_id = user["user_id"]
        result = await analytics_service.get_resolved_discord_chats(
            user_id=user_id,
            page=page,
            page_size=page_size
        )
        
        return {"data": result}
        
    except Exception as e:
        logger.error(f"Error fetching resolved chats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch resolved chats"
        )


@router.get("/discord/chats/unresolved")
async def get_unresolved_chats(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=100, description="Number of items per page"),
    user=Depends(auth_service.get_current_user),
):
    """
    Get paginated unresolved Discord chats for the authenticated user.
    
    Query Parameters:
        - page: Page number (default: 1)
        - page_size: Number of chats per page (default: 10, max: 100)
    
    Returns:
        - chats: List of unresolved Discord chats
        - pagination: Pagination metadata
    """
    try:
        user_id = user["user_id"]
        result = await analytics_service.get_unresolved_discord_chats(
            user_id=user_id,
            page=page,
            page_size=page_size
        )
        
        return {"data": result}
        
    except Exception as e:
        logger.error(f"Error fetching unresolved chats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch unresolved chats"
        )
