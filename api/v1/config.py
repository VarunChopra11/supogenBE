from dotenv import load_dotenv
import os

class AuthConfig:
    def __init__(self):
        load_dotenv(override=True)
    
    @property
    def JWT_SECRET_KEY(self):
        return os.getenv("JWT_SECRET_KEY")

    @property
    def FERNET_SECRET_KEY(self):
        """Base64 urlsafe 32-byte key for cryptography.Fernet."""
        return os.getenv("FERNET_SECRET_KEY")
    
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
    
class AIConfig:
    def __init__(self):
        load_dotenv(override=True)

    @property
    def OPENAI_API_KEY(self):
        return os.getenv("OPENAI_API_KEY")
    
    @property
    def AZURE_OPENAI_API_KEY(self):
        """Primary Azure OpenAI API key (falls back to OPENAI_API_KEY if not set)."""
        return os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")

    @property
    def AZURE_OPENAI_ENDPOINT(self):
        """Azure OpenAI endpoint base URL, e.g. https://your-resource.openai.azure.com."""
        return os.getenv("AZURE_OPENAI_ENDPOINT")
    
class DeplyoymentConfig:
    def __init__(self):
        load_dotenv(override=True)

    @property
    def MODE(self):
        return os.getenv("MODE", "development")
    
    @property
    def DOMAIN(self):
        return os.getenv("DOMAIN", None)
        
auth_config = AuthConfig()
db_config = DBConfig()
ai_config = AIConfig()
deploymentConfig = DeplyoymentConfig()