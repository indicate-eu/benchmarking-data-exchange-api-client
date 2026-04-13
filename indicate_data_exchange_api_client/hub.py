import copy
import logging
from abc import abstractmethod, ABC
from typing import Optional

import requests
from pydantic import BaseModel, Field
from pydantic_core import Url

import indicate_data_exchange_api_client
from indicate_data_exchange_api_client import ApiClient, DefaultApi
from indicate_data_exchange_api_client.exceptions import UnauthorizedException, ForbiddenException


logger = logging.getLogger("hub")


class Configuration(BaseModel):
    """
    Configuration for accessing the hub: API endpoint and optional data for the authentication flow.
    """
    endpoint: Url = Field(...,
                          description="Base URL at which to contact the data exchange server, that is the INDICATE hub.")
    # Additional fields for authenticating against an Azure-based deployment.
    tenant_id: Optional[str] = Field(None, description="Tenant ID")
    sp_client_id: Optional[str] = Field(None, description="SP client ID")
    apim_app_id: Optional[str] = Field(None, description="APIM App ID")
    # Secret-based authentication
    sp_client_secret: Optional[str] = Field(None, description="SP client secret")
    # Certificate-based authentication
    cert_thumbprint: Optional[str] = Field(None, description="Thumbprint of the certificate that is used as the client credential.")
    cert_key: Optional[str] = Field(None, description="Private key material of the certificate that is used as the client credential. ")


class Hub(ABC):
    """
    This class encapsulates configuration and access aspects of the data exchange protocol.
    """

    def __init__(self, endpoint: str):
        self._configuration = indicate_data_exchange_api_client.configuration.Configuration(endpoint)
        self._client = ApiClient(self._configuration)
        self._api = DefaultApi(self._client)

    def __enter__(self):
        self._client.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._client.__exit__(exc_type, exc_val, exc_tb)

    def indicator_info(self, *args, **kwargs):
        logger.info("Calling indicator_info endpoint")
        return self._api.indicator_info_get(*args, **kwargs)

    def results(self, *args, **kwargs):
        logger.info("Calling results endpoint")
        return self._api.results_get(*args, **kwargs)

    def provider_results(self, parameters, *args, **kwargs):
        logger.info("Calling provider_results endpoint")
        return self._api.provider_results_post(parameters, *args, **kwargs)

    @staticmethod
    def from_configuration(configuration: Configuration):
        url = str(configuration.endpoint)
        # Strip trailing / if necessary since the generated API client expects the base path to not contain it.
        if url.endswith('/'):
            url = url[:-1]
        if (configuration.tenant_id is None
            and configuration.sp_client_id is None
            and configuration.apim_app_id is None):
            return SimpleHub(url)
        else:
            def check_options(options: list[str]):
                for option in options:
                    value = getattr(configuration, option)
                    if value is None:
                        raise RuntimeError(f"Missing configuration option: {option}")

            check_options([ 'tenant_id', 'sp_client_id', 'apim_app_id' ])
            if (configuration.cert_thumbprint is None
                and configuration.cert_key is None):
                check_options([ 'sp_client_secret' ])
                return AzureHubWithSecret(url,
                                          tenant_id=configuration.tenant_id,
                                          sp_client_id=configuration.sp_client_id,
                                          apim_app_id=configuration.apim_app_id,
                                          sp_client_secret=configuration.sp_client_secret)
            else:
                check_options([ 'cert_thumbprint', 'cert_key' ])
                return AzureHubWithCertificate(url,
                                               tenant_id=configuration.tenant_id,
                                               sp_client_id=configuration.sp_client_id,
                                               apim_app_id=configuration.apim_app_id,
                                               cert_thumbprint=configuration.cert_thumbprint,
                                               cert_key=configuration.cert_key)


class SimpleHub(Hub):
    """
    This subclass of Hub is intended for communicating with a local hub instance directly.
    """
    pass


class AzureHub(Hub, ABC):
    """"
    This abstract sublcass of Hub is intended for communicating with an Azure-hosted hub instance through the APIM gateway.

    Concrete subclasses implement authentication with different kinds of credentials.

    Each method retrieves an access token if none is cached and retries requests with a newly obtained access token if
    the request in question failed due to an authorization issue.
    """

    def __init__(self, endpoint: str, tenant_id: str, sp_client_id: str, apim_app_id: str):
        super().__init__(endpoint)
        # Store data for the authentication flow.
        self._tenant_id    = tenant_id
        self._sp_client_id = sp_client_id
        self._apim_app_id  = apim_app_id
        self._access_token = None
        # Wrap methods such that an Authorization header is added and (re-)authentication is performed when needed,
        # potentially in combination with retrying the request.
        for name in ['indicator_info', 'results', 'provider_results']:
            old_method = getattr(self, name)
            # _name and _old are required to work around the binding and closure semantics
            def new_method(*args, _headers = None, _name=name, _old=old_method, **kwargs):
                def call():
                    # Augment headers with an Authorization header which contains the access token.
                    access_token = self.access_token
                    effective_headers = copy.copy(_headers) if _headers is not None else dict()
                    effective_headers['Authorization'] = f"Bearer {access_token}"
                    effective_kwargs = copy.copy(kwargs)
                    if '_headers' in effective_kwargs:
                        del effective_kwargs['_headers']
                    return _old(*args, _headers = effective_headers, **effective_kwargs)
                # Try the call once and try again with a newly obtained access token if the first attempt fails due to
                # authorization issues.
                try:
                    return call()
                except (UnauthorizedException, ForbiddenException) as e:
                    logger.error(f"{_name} call failed with {str(e)}\nRetrying once with new access token")
                    # TODO(moringenj): are the above correct for "Not authorized"?
                    # Re-obtain the access token in case it has expired.
                    self._access_token = None
                    return call()
            setattr(self, name, new_method)

    @property
    def access_token(self):
        if self._access_token is None:
            logger.info("Obtaining access token ...")
            self._access_token = self.obtain_access_token()
            logger.info("Obtained access token")
        return self._access_token

    @abstractmethod
    def obtain_access_token(self):
        pass


class AzureHubWithSecret(AzureHub):
    """
    This subclass of AzureHub implements authentication with a client secret credential.
    """

    def __init__(self, endpoint: str, sp_client_secret: str, **kwargs):
        super().__init__(endpoint, **kwargs)
        self._sp_client_secret = sp_client_secret

    def obtain_access_token(self):
        token_url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        token_response = requests.post(
            token_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "client_id":     self._sp_client_id,
                "client_secret": self._sp_client_secret,
                "scope":         f"api://{self._apim_app_id}/.default",
                "grant_type":    "client_credentials"
            }
        )
        token_response.raise_for_status()
        return token_response.json()["access_token"]

class AzureHubWithCertificate(AzureHub):
    """
    This subclass of AzureHub implements authentication with a client certificate credential.
    """

    def __init__(self, endpoint: str, cert_thumbprint: str, cert_key: str, **kwargs):
        super().__init__(endpoint, **kwargs)
        self._cert_thumbprint = cert_thumbprint
        self._cert_key = cert_key

    def obtain_access_token(self):
        import msal
        client_credential = {
            "thumbprint": self._cert_thumbprint,
            "private_key": self._cert_key
        }
        app = msal.ConfidentialClientApplication(
            self._sp_client_id,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            client_credential=client_credential
        )
        scopes = [ f"api://{self._apim_app_id}/.default" ]
        result = app.acquire_token_for_client(scopes=scopes)
        if "access_token" in result:
            return result["access_token"]
        else:
            raise RuntimeError(result.get("error"))
