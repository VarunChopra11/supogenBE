from dotenv import load_dotenv
import os

class AuthConfig:
    def __init__(self):
        load_dotenv(override=True)
    
    @property
    def JWT_SECRET_KEY(self):
        return os.getenv("JWT_SECRET_KEY")
    
    @property
    def CLERK_JWKS_URL(self):
        return os.getenv("CLERK_JWKS_URL")
    
    @property
    def CLERK_AUDIENCE(self):
        return os.getenv("CLERK_AUDIENCE")
    
    @property
    def CLERK_ISSUER(self):
        return os.getenv("CLERK_ISSUER")
    
    @property
    def FRONTEND_URL(self):
        return os.getenv("FRONTEND_URL")

class DBConfig:
    def __init__(self):
        load_dotenv(override=True)

    @property
    def MONGO_URI(self):
        return os.getenv("MONGO_URI")

    @property
    def MONGO_DB_NAME(self):
        return os.getenv("MONGO_DB_NAME")
    
auth_config = AuthConfig()
db_config = DBConfig()