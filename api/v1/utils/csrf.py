from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer

security = HTTPBearer()

class CSRFVerification:
    def __init__(self):
        pass

    async def verify_csrf(self, request: Request):
        csrf_header = request.headers.get("x-csrf-token")
        csrf_cookie = request.cookies.get("csrf_token")
        
        if not csrf_header or not csrf_cookie:
            raise HTTPException(
                status_code=403, 
                detail="CSRF token missing from header or cookie"
            )
        
        if csrf_header != csrf_cookie:
            raise HTTPException(
                status_code=403, 
                detail="CSRF token verification failed"
            )
        
        return True


csrf_verification = CSRFVerification()