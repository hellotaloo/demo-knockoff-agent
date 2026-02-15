"""
Microsoft Teams Bot Service.

Handles sending and receiving messages via Microsoft Bot Framework.
For proactive messaging and conversational AI in Teams channels.
"""
import os
import logging
from dataclasses import dataclass
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


@dataclass
class TeamsConfig:
    """Teams Bot configuration from environment variables."""
    app_id: str
    app_password: str
    tenant_id: str

    @classmethod
    def from_env(cls) -> "TeamsConfig":
        """Load configuration from environment variables."""
        app_id = os.environ.get("MS_TEAMS_APP_ID", "")
        app_password = os.environ.get("MS_TEAMS_CLIENT_SECRET", "")
        tenant_id = os.environ.get("MS_TEAMS_TENANT_ID", "")

        if not all([app_id, app_password, tenant_id]):
            logger.warning("Teams configuration incomplete. Set MS_TEAMS_APP_ID, MS_TEAMS_CLIENT_SECRET, MS_TEAMS_TENANT_ID")

        return cls(
            app_id=app_id,
            app_password=app_password,
            tenant_id=tenant_id,
        )


class TeamsService:
    """
    Service for Microsoft Teams Bot Framework integration.

    Supports:
    - Receiving messages from Teams (via webhook)
    - Sending proactive messages to channels/users
    - OAuth token management
    """

    # Bot Framework OAuth endpoint - use tenant-specific endpoint for Single Tenant bots
    OAUTH_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    # Bot Framework API base URL (for EMEA region)
    BOT_API_URL = "https://smba.trafficmanager.net/emea"

    def __init__(self, config: Optional[TeamsConfig] = None):
        self.config = config or TeamsConfig.from_env()
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def get_access_token(self) -> str:
        """
        Get OAuth access token for Bot Framework API.

        Caches token until expiry.
        """
        import time

        # Return cached token if still valid (with 60s buffer)
        if self._access_token and time.time() < (self._token_expires_at - 60):
            return self._access_token

        # Request new token using tenant-specific endpoint
        oauth_url = self.OAUTH_URL_TEMPLATE.format(tenant_id=self.config.tenant_id)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                oauth_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.config.app_id,
                    "client_secret": self.config.app_password,
                    "scope": "https://api.botframework.com/.default",
                },
            )

            if response.status_code != 200:
                logger.error(f"Failed to get Teams token: {response.status_code} - {response.text}")
                raise Exception(f"Failed to authenticate with Teams: {response.text}")

            data = response.json()
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 3600)

            logger.info("Successfully obtained Teams access token")
            return self._access_token

    async def send_to_channel(
        self,
        service_url: str,
        conversation_id: str,
        message: str,
        bot_id: str = None,
        bot_name: str = "TalooBot",
    ) -> dict:
        """
        Send a message to a Teams channel.

        Args:
            service_url: The service URL from the conversation reference
                         (e.g., https://smba.trafficmanager.net/emea/)
            conversation_id: The channel conversation ID
            message: The message text to send
            bot_id: The bot's app ID (defaults to config app_id)
            bot_name: The bot's display name

        Returns:
            API response as dict
        """
        token = await self.get_access_token()

        # Ensure service_url doesn't have trailing slash
        service_url = service_url.rstrip("/")

        # Use config app_id if bot_id not provided
        bot_id = bot_id or self.config.app_id

        url = f"{service_url}/v3/conversations/{conversation_id}/activities"

        payload = {
            "type": "message",
            "text": message,
            "from": {
                "id": bot_id,
                "name": bot_name,
            },
            "conversation": {
                "id": conversation_id,
            },
        }

        logger.info(f"Sending message to {url}")
        logger.info(f"Payload: {payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")

            if response.status_code not in [200, 201, 202]:
                logger.error(f"Failed to send Teams message: {response.status_code} - {response.text}")
                raise Exception(f"Failed to send Teams message ({response.status_code}): {response.text}")

            logger.info(f"Successfully sent message to Teams channel {conversation_id}")
            # Handle empty response (202 Accepted often has no body)
            if response.text:
                return response.json()
            return {"status": "accepted"}

    async def send_channel_notification(
        self,
        service_url: str,
        conversation_id: str,
        message: str,
        bot_id: str = None,
        bot_name: str = "TalooBot",
    ) -> dict:
        """
        Send a message with @channel mention to notify everyone.

        Args:
            service_url: The service URL from the conversation reference
            conversation_id: The channel conversation ID
            message: The message text to send
            bot_id: The bot's app ID
            bot_name: The bot's display name

        Returns:
            API response as dict
        """
        token = await self.get_access_token()
        service_url = service_url.rstrip("/")
        bot_id = bot_id or self.config.app_id

        url = f"{service_url}/v3/conversations/{conversation_id}/activities"

        # Use channelData.notification.alert to force notification
        payload = {
            "type": "message",
            "text": message,
            "importance": "high",
            "from": {
                "id": bot_id,
                "name": bot_name,
            },
            "conversation": {
                "id": conversation_id,
            },
            "channelData": {
                "notification": {
                    "alert": True,
                    "alertInMeeting": True,
                }
            },
        }

        logger.info(f"Sending notification to {url}")
        logger.info(f"Payload: {payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")

            if response.status_code not in [200, 201, 202]:
                logger.error(f"Failed to send Teams notification: {response.status_code} - {response.text}")
                raise Exception(f"Failed to send Teams notification ({response.status_code}): {response.text}")

            if response.text:
                return response.json()
            return {"status": "accepted"}

    async def send_with_mention(
        self,
        service_url: str,
        conversation_id: str,
        message: str,
        mention_user_id: str,
        mention_user_name: str,
        bot_id: str = None,
        bot_name: str = "TalooBot",
    ) -> dict:
        """
        Send a message with @mention to notify a specific user.

        Args:
            service_url: The service URL from the conversation reference
            conversation_id: The channel conversation ID
            message: The message text to send
            mention_user_id: The Teams user ID to @mention
            mention_user_name: The display name for the mention
            bot_id: The bot's app ID
            bot_name: The bot's display name

        Returns:
            API response as dict
        """
        token = await self.get_access_token()
        service_url = service_url.rstrip("/")
        bot_id = bot_id or self.config.app_id

        url = f"{service_url}/v3/conversations/{conversation_id}/activities"

        # Proper @mention format for Teams
        payload = {
            "type": "message",
            "text": f"<at>{mention_user_name}</at> {message}",
            "from": {
                "id": bot_id,
                "name": bot_name,
            },
            "conversation": {
                "id": conversation_id,
            },
            "entities": [
                {
                    "type": "mention",
                    "text": f"<at>{mention_user_name}</at>",
                    "mentioned": {
                        "id": mention_user_id,
                        "name": mention_user_name,
                    },
                }
            ],
        }

        logger.info(f"Sending message with @mention to {url}")
        logger.info(f"Payload: {payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")

            if response.status_code not in [200, 201, 202]:
                logger.error(f"Failed to send Teams mention: {response.status_code} - {response.text}")
                raise Exception(f"Failed to send Teams mention ({response.status_code}): {response.text}")

            if response.text:
                return response.json()
            return {"status": "accepted"}

    async def send_card_to_channel(
        self,
        service_url: str,
        conversation_id: str,
        card: dict,
    ) -> dict:
        """
        Send an Adaptive Card to a Teams channel.

        Args:
            service_url: The service URL from the conversation reference
            conversation_id: The channel conversation ID
            card: Adaptive Card JSON object

        Returns:
            API response as dict
        """
        token = await self.get_access_token()
        service_url = service_url.rstrip("/")

        url = f"{service_url}/v3/conversations/{conversation_id}/activities"

        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code not in [200, 201]:
                logger.error(f"Failed to send Teams card: {response.status_code} - {response.text}")
                raise Exception(f"Failed to send Teams card: {response.text}")

            logger.info(f"Successfully sent card to Teams channel {conversation_id}")
            return response.json()

    async def reply_to_activity(
        self,
        service_url: str,
        conversation_id: str,
        activity_id: str,
        message: str,
        bot_id: str = None,
        bot_name: str = "TalooBot",
    ) -> dict:
        """
        Reply to a specific activity (message) in Teams.

        Args:
            service_url: The service URL from the incoming activity
            conversation_id: The conversation ID
            activity_id: The activity ID to reply to
            message: The reply text
            bot_id: The bot's app ID (defaults to config app_id)
            bot_name: The bot's display name

        Returns:
            API response as dict
        """
        token = await self.get_access_token()
        service_url = service_url.rstrip("/")

        # Use config app_id if bot_id not provided
        bot_id = bot_id or self.config.app_id

        url = f"{service_url}/v3/conversations/{conversation_id}/activities"

        payload = {
            "type": "message",
            "text": message,
            "from": {
                "id": bot_id,
                "name": bot_name,
            },
            "conversation": {
                "id": conversation_id,
            },
            "replyToId": activity_id,
        }

        logger.info(f"Sending reply to {url}")
        logger.info(f"Payload: {payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )

            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")

            if response.status_code not in [200, 201, 202]:
                logger.error(f"Failed to reply in Teams: {response.status_code} - {response.text}")
                raise Exception(f"Failed to reply in Teams ({response.status_code}): {response.text}")

            # Handle empty response (202 Accepted often has no body)
            if response.text:
                return response.json()
            return {"status": "accepted"}

    def parse_incoming_activity(self, activity: dict) -> dict:
        """
        Parse an incoming Bot Framework activity.

        Args:
            activity: The raw activity from Teams webhook

        Returns:
            Parsed activity with key fields extracted
        """
        return {
            "type": activity.get("type"),
            "id": activity.get("id"),
            "timestamp": activity.get("timestamp"),
            "service_url": activity.get("serviceUrl"),
            "channel_id": activity.get("channelId"),
            "conversation": {
                "id": activity.get("conversation", {}).get("id"),
                "name": activity.get("conversation", {}).get("name"),
                "tenant_id": activity.get("conversation", {}).get("tenantId"),
            },
            "from": {
                "id": activity.get("from", {}).get("id"),
                "name": activity.get("from", {}).get("name"),
            },
            "recipient": {
                "id": activity.get("recipient", {}).get("id"),
                "name": activity.get("recipient", {}).get("name"),
            },
            "text": activity.get("text", ""),
            "text_format": activity.get("textFormat"),
        }


# Singleton instance
teams_service = TeamsService()


def get_teams_service() -> TeamsService:
    """Get the Teams service singleton."""
    return teams_service
