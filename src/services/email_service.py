"""
Email service - handles transactional emails via Resend.
"""
import logging
from typing import Optional

import resend

from src.config import RESEND_API_KEY, EMAIL_FROM_ADDRESS, EMAIL_FROM_NAME, FRONTEND_URL

logger = logging.getLogger(__name__)

# Initialize Resend
resend.api_key = RESEND_API_KEY


class EmailService:
    """Service for sending transactional emails via Resend."""

    @staticmethod
    def _is_configured() -> bool:
        """Check if email sending is configured."""
        return bool(RESEND_API_KEY)

    @staticmethod
    async def send_workspace_invitation(
        to_email: str,
        workspace_name: str,
        inviter_name: str,
        role: str,
        invitation_token: str,
    ) -> Optional[str]:
        """
        Send a workspace invitation email.

        Args:
            to_email: Recipient email address
            workspace_name: Name of the workspace
            inviter_name: Name of the person who sent the invitation
            role: Role being assigned (admin/member)
            invitation_token: Token for accepting the invitation

        Returns:
            Resend email ID if sent, None if email is not configured
        """
        if not EmailService._is_configured():
            logger.warning("Email not configured (RESEND_API_KEY missing), skipping invitation email")
            return None

        accept_url = f"{FRONTEND_URL}/invite?token={invitation_token}"
        role_label = "beheerder" if role == "admin" else "lid"

        html = f"""
        <!DOCTYPE html>
        <html lang="nl">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #f4f4f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f4f5; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 480px; background-color: #ffffff; border-radius: 12px; overflow: hidden;">
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #18181b; padding: 32px 40px; text-align: center;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600; letter-spacing: -0.5px;">TALOO</h1>
                                </td>
                            </tr>
                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 8px; color: #18181b; font-size: 20px; font-weight: 600;">
                                        Je bent uitgenodigd!
                                    </h2>
                                    <p style="margin: 0 0 24px; color: #52525b; font-size: 15px; line-height: 1.6;">
                                        <strong>{inviter_name}</strong> heeft je uitgenodigd om als <strong>{role_label}</strong> deel te nemen aan de workspace <strong>{workspace_name}</strong> op Taloo.
                                    </p>
                                    <!-- CTA Button -->
                                    <table width="100%" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td align="center" style="padding: 8px 0 24px;">
                                                <a href="{accept_url}"
                                                   style="display: inline-block; background-color: #18181b; color: #ffffff; text-decoration: none; font-size: 15px; font-weight: 500; padding: 12px 32px; border-radius: 8px;">
                                                    Uitnodiging accepteren
                                                </a>
                                            </td>
                                        </tr>
                                    </table>
                                    <p style="margin: 0 0 4px; color: #a1a1aa; font-size: 13px; line-height: 1.5;">
                                        Deze uitnodiging is 7 dagen geldig. Als je de knop niet kunt gebruiken, kopieer dan deze link:
                                    </p>
                                    <p style="margin: 0; color: #a1a1aa; font-size: 12px; word-break: break-all;">
                                        {accept_url}
                                    </p>
                                </td>
                            </tr>
                            <!-- Footer -->
                            <tr>
                                <td style="padding: 20px 40px 28px; border-top: 1px solid #f4f4f5;">
                                    <p style="margin: 0; color: #a1a1aa; font-size: 12px; text-align: center;">
                                        &copy; Taloo &middot; AI-powered recruitment
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        try:
            result = resend.Emails.send({
                "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>",
                "to": [to_email],
                "subject": f"{inviter_name} heeft je uitgenodigd voor {workspace_name}",
                "html": html,
            })
            email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
            logger.info(f"Invitation email sent to {to_email} (id: {email_id})")
            return email_id
        except Exception as e:
            logger.error(f"Failed to send invitation email to {to_email}: {e}")
            return None

    @staticmethod
    async def send_workspace_added_notification(
        to_email: str,
        workspace_name: str,
        inviter_name: str,
        role: str,
    ) -> Optional[str]:
        """
        Send a notification when a user is directly added to a workspace
        (they already have a Taloo account).

        Args:
            to_email: Recipient email address
            workspace_name: Name of the workspace
            inviter_name: Name of the person who added them
            role: Role assigned (admin/member)

        Returns:
            Resend email ID if sent, None if email is not configured
        """
        if not EmailService._is_configured():
            logger.warning("Email not configured (RESEND_API_KEY missing), skipping notification email")
            return None

        dashboard_url = f"{FRONTEND_URL}"
        role_label = "beheerder" if role == "admin" else "lid"

        html = f"""
        <!DOCTYPE html>
        <html lang="nl">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="margin: 0; padding: 0; background-color: #f4f4f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #f4f4f5; padding: 40px 20px;">
                <tr>
                    <td align="center">
                        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 480px; background-color: #ffffff; border-radius: 12px; overflow: hidden;">
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #18181b; padding: 32px 40px; text-align: center;">
                                    <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 600; letter-spacing: -0.5px;">TALOO</h1>
                                </td>
                            </tr>
                            <!-- Body -->
                            <tr>
                                <td style="padding: 40px;">
                                    <h2 style="margin: 0 0 8px; color: #18181b; font-size: 20px; font-weight: 600;">
                                        Je bent toegevoegd!
                                    </h2>
                                    <p style="margin: 0 0 24px; color: #52525b; font-size: 15px; line-height: 1.6;">
                                        <strong>{inviter_name}</strong> heeft je als <strong>{role_label}</strong> toegevoegd aan de workspace <strong>{workspace_name}</strong> op Taloo. Je kunt er meteen aan de slag.
                                    </p>
                                    <!-- CTA Button -->
                                    <table width="100%" cellpadding="0" cellspacing="0">
                                        <tr>
                                            <td align="center" style="padding: 8px 0 24px;">
                                                <a href="{dashboard_url}"
                                                   style="display: inline-block; background-color: #18181b; color: #ffffff; text-decoration: none; font-size: 15px; font-weight: 500; padding: 12px 32px; border-radius: 8px;">
                                                    Ga naar Taloo
                                                </a>
                                            </td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>
                            <!-- Footer -->
                            <tr>
                                <td style="padding: 20px 40px 28px; border-top: 1px solid #f4f4f5;">
                                    <p style="margin: 0; color: #a1a1aa; font-size: 12px; text-align: center;">
                                        &copy; Taloo &middot; AI-powered recruitment
                                    </p>
                                </td>
                            </tr>
                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

        try:
            result = resend.Emails.send({
                "from": f"{EMAIL_FROM_NAME} <{EMAIL_FROM_ADDRESS}>",
                "to": [to_email],
                "subject": f"Je bent toegevoegd aan {workspace_name}",
                "html": html,
            })
            email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
            logger.info(f"Added notification email sent to {to_email} (id: {email_id})")
            return email_id
        except Exception as e:
            logger.error(f"Failed to send added notification email to {to_email}: {e}")
            return None
