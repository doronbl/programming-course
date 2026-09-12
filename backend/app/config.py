"""Application configuration.

Values are read from environment variables set by the ECS task definition in
infra/compute.yaml. The env var names here MUST match that template exactly.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings sourced from the environment.

    Environment variables (set by infra/compute.yaml):
      COGNITO_USER_POOL_ID  - Cognito user pool id.
      COGNITO_REGION        - AWS region of the Cognito user pool.
      COGNITO_CLIENT_ID     - Cognito app client id (JWT audience for id tokens).
      COGNITO_ISSUER        - Token issuer URL. Built from region + pool id when unset.
      AWS_REGION            - AWS region used by boto3 clients.
      CONTENT_BUCKET        - S3 bucket holding course content.
      PORT                  - Port uvicorn binds to inside the container.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    cognito_user_pool_id: str = ""
    cognito_region: str = "us-east-1"
    cognito_client_id: str = ""
    cognito_issuer: str = ""
    aws_region: str = "us-east-1"
    content_bucket: str = ""
    port: int = 8000

    @model_validator(mode="after")
    def _default_issuer(self) -> "Settings":
        if not self.cognito_issuer and self.cognito_user_pool_id:
            self.cognito_issuer = (
                f"https://cognito-idp.{self.cognito_region}.amazonaws.com/"
                f"{self.cognito_user_pool_id}"
            )
        return self

    @property
    def jwks_url(self) -> str:
        """URL of the Cognito JSON Web Key Set for this user pool."""
        return f"{self.cognito_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
