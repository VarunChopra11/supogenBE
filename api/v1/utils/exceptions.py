# Discord Authentication Exceptions
class AuthenticationError(Exception):
    """Base exception for authentication errors."""
    pass


class ServerAlreadyRegisteredError(AuthenticationError):
    """Raised when a Discord server is already registered with the bot."""
    pass


class TokenAlreadyUsedError(AuthenticationError):
    """Raised when a JWT token has already been used for server registration."""
    pass


class UserNotFoundError(AuthenticationError):
    """Raised when a user is not found in the database."""
    pass


class InvalidTokenError(AuthenticationError):
    """Raised when a JWT token is invalid or expired."""
    pass


class DatabaseError(AuthenticationError):
    """Raised when there's a database connection or operation issue."""
    pass
