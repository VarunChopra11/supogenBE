from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional
from api.v1.services.auth_services.auth import AuthService
from api.v1.schemas.users import UserResponse
from api.v1.config import deploymentConfig


router = APIRouter(prefix="/auth", tags=["auth"])

bearer = HTTPBearer(auto_error=False)
auth_service = AuthService()

@router.get("/handshake")
async def handshake(
    request: Request,
    response: Response,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)
):
    # Prefer explicit Authorization header; fall back to parsed creds
    authorization = request.headers.get("Authorization")
    if not authorization and creds:
        authorization = f"{creds.scheme} {creds.credentials}"

    if not authorization:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Missing Authorization header"}
        )

    try:
        result = await auth_service.handshake_service(authorization)

        # Create a proper JSON response and set cookie on it
        resp = JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "message": "Handshake successful",
            },
        )

        
        if deploymentConfig.MODE == "development":
            domain = None
        else:
            domain = deploymentConfig.DOMAIN

        resp.set_cookie(
            key="access_token",
            value=result["token"],
            max_age=auth_service.JWT_TOKEN_EXPIRE_MINUTES * 60,
            httponly=True,
            secure=True,
            samesite="none",
            domain=domain,
        )
        return resp

    except HTTPException as http_exc:
        return JSONResponse(
            status_code=http_exc.status_code,
            content={"error": http_exc.detail}
        )
    except Exception as e:
        print("Error in authentication:", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error during authentication."}
        )
    
@router.get("/session")
async def get_user(request: Request, response: Response):
    try:
        user = await auth_service.get_current_user(request)
        csrf_token = auth_service.generate_csrf_token()

        user_response = UserResponse(
            user_id=user["user_id"],
            email=user["email"],
            name=user["name"],
            picture=user["picture"],
        )

        resp = JSONResponse(
            content={
            "user": user_response.model_dump(),
            "csrf_token": csrf_token
            },
            status_code=status.HTTP_200_OK
        )

        if deploymentConfig.MODE == "development":
            domain = None
        else:
            domain = deploymentConfig.DOMAIN

        resp.set_cookie(
            key="csrf_token",
            value=csrf_token,
            max_age=5 * 60 * 60,  # 5 hours
            httponly=True,
            secure=True,
            samesite="none",
            domain=domain,
        )
        return resp
    
    except HTTPException as http_exc:
        return JSONResponse(
            status_code=http_exc.status_code,
            content={"error": http_exc.detail}
        )
    
    except Exception as e:
        print("Error in get_current_user:", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error while fetching user."}
        )
    
@router.post("/logout")
async def logout():
    response = Response(content="Logged out successfully")

    if deploymentConfig.MODE == "development":
        domain = None
    else:
        domain = deploymentConfig.DOMAIN

    # Delete access_token cookie
    response.delete_cookie(
        key="access_token",
        domain=domain,
        secure=True,
        httponly=True,
        samesite="none"
    )
    # Delete csrf_token cookie
    response.delete_cookie(
        key="csrf_token",
        domain=domain,
        secure=True,
        httponly=True,
        samesite="none"
    )
    return response
