"""
Google Drive Service for creating screening notes documents.

This module provides functionality to:
1. Create Google Docs with rich formatting (tables, colors, etc.)
2. Share documents with specific users
3. Get document links for calendar event attachments

Uses Service Account with Domain-Wide Delegation for Workspace access.
"""

import os
import logging
from typing import Optional, List, Dict, Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


# Scopes required for Google Drive and Docs
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/documents",
]

# Google Docs default colors (RGB 0-1 scale)
COLORS = {
    # Google Docs default palette
    "green": {"red": 0.2, "green": 0.66, "blue": 0.33},           # #34A853 - qualified/passed
    "light_green_bg": {"red": 0.85, "green": 0.92, "blue": 0.85}, # Light green background
    "red": {"red": 0.92, "green": 0.26, "blue": 0.21},            # #EA4335 - failed/low score
    "orange": {"red": 1.0, "green": 0.6, "blue": 0.0},            # Orange - average
    "yellow": {"red": 0.98, "green": 0.74, "blue": 0.02},         # #FBBC05 - warning
    "gray": {"red": 0.4, "green": 0.4, "blue": 0.4},              # #666666 - metadata
    "light_gray": {"red": 0.8, "green": 0.8, "blue": 0.8},        # Divider
    "black": {"red": 0, "green": 0, "blue": 0},
    "white": {"red": 1, "green": 1, "blue": 1},
}


class GoogleDriveService:
    """Service for creating Google Docs screening notes with rich formatting."""

    def __init__(self):
        self._drive_service = None
        self._docs_service = None
        self._credentials = None

    def _get_credentials(self, impersonate_email: Optional[str] = None):
        service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if not service_account_file:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_FILE environment variable is required.")

        subject = impersonate_email or os.environ.get("GOOGLE_CALENDAR_IMPERSONATE_EMAIL")

        credentials = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=DRIVE_SCOPES,
            subject=subject,
        )
        return credentials

    def _get_drive_service(self, impersonate_email: Optional[str] = None):
        if impersonate_email:
            credentials = self._get_credentials(impersonate_email)
            return build("drive", "v3", credentials=credentials, cache_discovery=False)

        if self._drive_service is None:
            self._credentials = self._get_credentials()
            self._drive_service = build("drive", "v3", credentials=self._credentials, cache_discovery=False)

        return self._drive_service

    def _get_docs_service(self, impersonate_email: Optional[str] = None):
        if impersonate_email:
            credentials = self._get_credentials(impersonate_email)
            return build("docs", "v1", credentials=credentials, cache_discovery=False)

        if self._docs_service is None:
            self._credentials = self._get_credentials()
            self._docs_service = build("docs", "v1", credentials=self._credentials, cache_discovery=False)

        return self._docs_service

    async def create_screening_notes_doc(
        self,
        owner_email: str,
        title: str,
        content: str,
        folder_id: Optional[str] = None,
    ) -> dict:
        """Create a Google Doc with screening notes content (legacy plain text)."""
        try:
            docs_service = self._get_docs_service(impersonate_email=owner_email)

            doc = docs_service.documents().create(body={"title": title}).execute()
            doc_id = doc.get("documentId")

            logger.info(f"Created Google Doc: {doc_id} - {title}")

            if content:
                requests = self._build_document_requests(content)
                if requests:
                    docs_service.documents().batchUpdate(
                        documentId=doc_id,
                        body={"requests": requests}
                    ).execute()

            if folder_id:
                drive_service = self._get_drive_service(impersonate_email=owner_email)
                drive_service.files().update(
                    fileId=doc_id,
                    addParents=folder_id,
                    fields="id, parents"
                ).execute()

            drive_service = self._get_drive_service(impersonate_email=owner_email)
            file_info = drive_service.files().get(
                fileId=doc_id,
                fields="id, name, webViewLink"
            ).execute()

            return {
                "id": doc_id,
                "title": title,
                "webViewLink": file_info.get("webViewLink"),
            }

        except HttpError as e:
            logger.error(f"Failed to create Google Doc: {e}")
            raise

    async def create_rich_screening_doc(
        self,
        owner_email: str,
        title: str,
        sections: List[Dict[str, Any]],
        folder_id: Optional[str] = None,
    ) -> dict:
        """
        Create a Google Doc with rich formatting using structured sections.
        """
        try:
            docs_service = self._get_docs_service(impersonate_email=owner_email)

            doc = docs_service.documents().create(body={"title": title}).execute()
            doc_id = doc.get("documentId")

            logger.info(f"Created Google Doc: {doc_id} - {title}")

            if sections:
                requests = self._build_rich_requests(sections)
                if requests:
                    docs_service.documents().batchUpdate(
                        documentId=doc_id,
                        body={"requests": requests}
                    ).execute()

            if folder_id:
                drive_service = self._get_drive_service(impersonate_email=owner_email)
                drive_service.files().update(
                    fileId=doc_id,
                    addParents=folder_id,
                    fields="id, parents"
                ).execute()

            drive_service = self._get_drive_service(impersonate_email=owner_email)
            file_info = drive_service.files().get(
                fileId=doc_id,
                fields="id, name, webViewLink"
            ).execute()

            return {
                "id": doc_id,
                "title": title,
                "webViewLink": file_info.get("webViewLink"),
            }

        except HttpError as e:
            logger.error(f"Failed to create Google Doc: {e}")
            raise

    def _build_rich_requests(self, sections: List[Dict[str, Any]]) -> list:
        """Build Google Docs API requests from structured sections."""
        requests = []
        idx = 1  # Current document index

        for section in sections:
            section_type = section.get("type", "paragraph")

            if section_type == "header":
                # Main title - Arial 18pt, bold, underlined
                text = section.get("content", "")
                requests.append({"insertText": {"location": {"index": idx}, "text": text + "\n"}})
                # Style the text (excluding newline)
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(text)},
                        "textStyle": {
                            "bold": True,
                            "underline": True,
                            "fontSize": {"magnitude": 18, "unit": "PT"},
                            "weightedFontFamily": {"fontFamily": "Arial"}
                        },
                        "fields": "bold,underline,fontSize,weightedFontFamily"
                    }
                })
                idx += len(text) + 1  # +1 for newline
                # Add blank line
                requests.append({"insertText": {"location": {"index": idx}, "text": "\n"}})
                idx += 1

            elif section_type == "metadata":
                # Small gray metadata line
                text = section.get("content", "")
                requests.append({"insertText": {"location": {"index": idx}, "text": text + "\n\n"}})
                # Style the text (excluding newlines)
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(text)},
                        "textStyle": {
                            "fontSize": {"magnitude": 9, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": COLORS["gray"]}},
                            "weightedFontFamily": {"fontFamily": "Arial"}
                        },
                        "fields": "fontSize,foregroundColor,weightedFontFamily"
                    }
                })
                idx += len(text) + 2  # +2 for two newlines

            elif section_type == "section_header":
                # Section header with emoji - Arial 11, bold
                emoji = section.get("emoji", "")
                title = section.get("content", "")
                text = f"{emoji} {title}" if emoji else title
                requests.append({"insertText": {"location": {"index": idx}, "text": text + "\n"}})
                # Style the text (excluding newline)
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(text)},
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 11, "unit": "PT"},
                            "weightedFontFamily": {"fontFamily": "Arial"}
                        },
                        "fields": "bold,fontSize,weightedFontFamily"
                    }
                })
                idx += len(text) + 1  # +1 for newline
                # Add blank line after header
                requests.append({"insertText": {"location": {"index": idx}, "text": "\n"}})
                idx += 1

            elif section_type == "summary_box":
                # Green background summary box (using indentation to simulate)
                summary = section.get("content", "")
                # Note: True table backgrounds require more complex API calls
                # Using a simple bordered text approach
                text = f"{summary}\n\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": text}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(text) - 2},
                        "textStyle": {
                            "italic": True,
                            "fontSize": {"magnitude": 11, "unit": "PT"},
                            "weightedFontFamily": {"fontFamily": "Arial"},
                            "backgroundColor": {"color": {"rgbColor": COLORS["light_green_bg"]}}
                        },
                        "fields": "italic,fontSize,weightedFontFamily,backgroundColor"
                    }
                })
                idx += len(text)

            elif section_type == "status_table":
                # Status information as formatted lines
                status = section.get("status", "Afgerond")
                qualified = section.get("qualified", False)
                score = section.get("score")
                duration = section.get("duration", "")
                questions = section.get("questions", 0)

                # Build table-like text
                lines = []
                lines.append(f"Status\t\t\t{status}")
                qual_text = "✓ Gekwalificeerd" if qualified else "✗ Niet gekwalificeerd"
                lines.append(f"Kwalificatie\t\t{qual_text}")
                if score is not None:
                    lines.append(f"Score\t\t\t{score}/100")
                lines.append(f"Duur\t\t\t{duration}")
                lines.append(f"Vragen\t\t\t{questions}")

                for i, line in enumerate(lines):
                    text = line + "\n"
                    requests.append({"insertText": {"location": {"index": idx}, "text": text}})

                    # Make label bold
                    tab_pos = line.find("\t")
                    if tab_pos > 0:
                        requests.append({
                            "updateTextStyle": {
                                "range": {"startIndex": idx, "endIndex": idx + tab_pos},
                                "textStyle": {"bold": True, "fontSize": {"magnitude": 11, "unit": "PT"}},
                                "fields": "bold,fontSize"
                            }
                        })

                    # Color the qualification value
                    if "Kwalificatie" in line:
                        value_start = idx + tab_pos + 3  # After tabs
                        value_end = idx + len(text) - 1
                        color = COLORS["green"] if qualified else COLORS["red"]
                        requests.append({
                            "updateTextStyle": {
                                "range": {"startIndex": value_start, "endIndex": value_end},
                                "textStyle": {"foregroundColor": {"color": {"rgbColor": color}}},
                                "fields": "foregroundColor"
                            }
                        })

                    idx += len(text)

                # Add spacing
                requests.append({"insertText": {"location": {"index": idx}, "text": "\n"}})
                idx += 1

            elif section_type == "contact_info":
                # Contact information
                name = section.get("name", "")
                phone = section.get("phone", "")
                email = section.get("email", "")

                text = f"Naam: {name}\n"
                if phone:
                    text += f"Telefoon: {phone}\n"
                if email:
                    text += f"Email: {email}\n"
                text += "\n"

                requests.append({"insertText": {"location": {"index": idx}, "text": text}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(text) - 1},
                        "textStyle": {"fontSize": {"magnitude": 11, "unit": "PT"}},
                        "fields": "fontSize"
                    }
                })
                idx += len(text)

            elif section_type == "qa_knockout":
                # Knockout question with pass/fail
                question = section.get("question", "")
                answer = section.get("answer", "")
                passed = section.get("passed", False)

                # Question line with red ?
                q_text = f"❓ {question}\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": q_text}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(q_text) - 1},
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 11, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": COLORS["red"]}}
                        },
                        "fields": "bold,fontSize,foregroundColor"
                    }
                })
                # Make just the question text black
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx + 2, "endIndex": idx + len(q_text) - 1},
                        "textStyle": {"foregroundColor": {"color": {"rgbColor": COLORS["black"]}}},
                        "fields": "foregroundColor"
                    }
                })
                idx += len(q_text)

                # Answer line
                a_text = f'Antwoord: "{answer}"\n'
                requests.append({"insertText": {"location": {"index": idx}, "text": a_text}})
                # Italicize the answer
                quote_start = idx + 10  # After "Antwoord: "
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": quote_start, "endIndex": idx + len(a_text) - 1},
                        "textStyle": {"italic": True, "fontSize": {"magnitude": 11, "unit": "PT"}},
                        "fields": "italic,fontSize"
                    }
                })
                idx += len(a_text)

                # Result line
                result_text = "✓ Geslaagd" if passed else "✗ Niet geslaagd"
                r_text = f"Resultaat: {result_text}\n\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": r_text}})
                # Color the result
                result_start = idx + 11  # After "Resultaat: "
                color = COLORS["green"] if passed else COLORS["red"]
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": result_start, "endIndex": idx + len(r_text) - 2},
                        "textStyle": {"foregroundColor": {"color": {"rgbColor": color}}},
                        "fields": "foregroundColor"
                    }
                })
                idx += len(r_text)

            elif section_type == "qa_qualification":
                # Qualification question with score
                question = section.get("question", "")
                answer = section.get("answer", "")
                score = section.get("score", 0)
                rating = section.get("rating", "")
                motivation = section.get("motivation", "")

                # Determine color based on score
                if score >= 70:
                    score_color = COLORS["green"]
                elif score >= 40:
                    score_color = COLORS["orange"]
                else:
                    score_color = COLORS["red"]

                rating_dutch = {
                    "weak": "Zwak", "below_average": "Onder gemiddeld",
                    "average": "Gemiddeld", "good": "Goed", "excellent": "Uitstekend"
                }.get(rating, rating)

                # Question line
                q_text = f"❓ {question}\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": q_text}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(q_text) - 1},
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 11, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": COLORS["red"]}}
                        },
                        "fields": "bold,fontSize,foregroundColor"
                    }
                })
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx + 2, "endIndex": idx + len(q_text) - 1},
                        "textStyle": {"foregroundColor": {"color": {"rgbColor": COLORS["black"]}}},
                        "fields": "foregroundColor"
                    }
                })
                idx += len(q_text)

                # Answer line
                a_text = f'Antwoord: "{answer}"\n'
                requests.append({"insertText": {"location": {"index": idx}, "text": a_text}})
                quote_start = idx + 10
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": quote_start, "endIndex": idx + len(a_text) - 1},
                        "textStyle": {"italic": True, "fontSize": {"magnitude": 11, "unit": "PT"}},
                        "fields": "italic,fontSize"
                    }
                })
                idx += len(a_text)

                # Score line
                s_text = f"Score: {score}/100 ({rating_dutch})\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": s_text}})
                score_start = idx + 7  # After "Score: "
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": score_start, "endIndex": idx + len(s_text) - 1},
                        "textStyle": {
                            "bold": True,
                            "foregroundColor": {"color": {"rgbColor": score_color}}
                        },
                        "fields": "bold,foregroundColor"
                    }
                })
                idx += len(s_text)

                # Motivation if present
                if motivation:
                    m_text = f"💡 {motivation}\n"
                    requests.append({"insertText": {"location": {"index": idx}, "text": m_text}})
                    requests.append({
                        "updateTextStyle": {
                            "range": {"startIndex": idx, "endIndex": idx + len(m_text) - 1},
                            "textStyle": {
                                "fontSize": {"magnitude": 10, "unit": "PT"},
                                "foregroundColor": {"color": {"rgbColor": COLORS["gray"]}}
                            },
                            "fields": "fontSize,foregroundColor"
                        }
                    })
                    idx += len(m_text)

                # Spacing between questions
                requests.append({"insertText": {"location": {"index": idx}, "text": "\n\n"}})
                idx += 2

            elif section_type == "divider":
                text = "─" * 60 + "\n\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": text}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(text) - 1},
                        "textStyle": {"foregroundColor": {"color": {"rgbColor": COLORS["light_gray"]}}},
                        "fields": "foregroundColor"
                    }
                })
                idx += len(text)

            elif section_type == "vacancy_box":
                # Vacancy section
                vacancy_title = section.get("title", "")
                vacancy_text = section.get("content", "")

                header = f"📁 VACATURE: {vacancy_title}\n\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": header}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(header) - 1},
                        "textStyle": {
                            "bold": True,
                            "fontSize": {"magnitude": 11, "unit": "PT"}
                        },
                        "fields": "bold,fontSize"
                    }
                })
                idx += len(header)

                # Vacancy content
                content = vacancy_text + "\n\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": content}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(content) - 1},
                        "textStyle": {
                            "fontSize": {"magnitude": 10, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": COLORS["gray"]}}
                        },
                        "fields": "fontSize,foregroundColor"
                    }
                })
                idx += len(content)

            elif section_type == "spacing":
                # Extra vertical spacing
                requests.append({"insertText": {"location": {"index": idx}, "text": "\n\n"}})
                idx += 2

            elif section_type == "candidate_history":
                # Candidate context/history section
                context_text = section.get("content", "")
                if context_text:
                    requests.append({"insertText": {"location": {"index": idx}, "text": context_text + "\n"}})
                    idx += len(context_text) + 1

            elif section_type == "footer":
                text = section.get("content", "") + "\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": text}})
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": idx, "endIndex": idx + len(text) - 1},
                        "textStyle": {
                            "fontSize": {"magnitude": 9, "unit": "PT"},
                            "foregroundColor": {"color": {"rgbColor": COLORS["gray"]}},
                            "italic": True
                        },
                        "fields": "fontSize,foregroundColor,italic"
                    }
                })
                idx += len(text)

            else:
                # Default paragraph
                text = section.get("content", "") + "\n"
                requests.append({"insertText": {"location": {"index": idx}, "text": text}})
                idx += len(text)

        return requests

    def _build_document_requests(self, content: str) -> list:
        """Build Google Docs API requests from markdown-like content (legacy)."""
        requests = []
        idx = 1

        lines = content.split("\n")

        for line in lines:
            if not line.strip():
                requests.append({"insertText": {"location": {"index": idx}, "text": "\n"}})
                idx += 1
                continue

            text = line + "\n"
            requests.append({"insertText": {"location": {"index": idx}, "text": text}})

            start = idx
            end = idx + len(text) - 1

            if line.startswith("# "):
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"bold": True, "fontSize": {"magnitude": 18, "unit": "PT"}},
                        "fields": "bold,fontSize"
                    }
                })
            elif line.startswith("## "):
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"bold": True, "fontSize": {"magnitude": 14, "unit": "PT"}},
                        "fields": "bold,fontSize"
                    }
                })
            elif line.startswith("### "):
                requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {"bold": True, "fontSize": {"magnitude": 12, "unit": "PT"}},
                        "fields": "bold,fontSize"
                    }
                })

            idx += len(text)

        return requests

    async def share_document(
        self,
        owner_email: str,
        doc_id: str,
        share_with_email: str,
        role: str = "reader"
    ):
        """Share a document with another user."""
        try:
            drive_service = self._get_drive_service(impersonate_email=owner_email)

            permission = {
                "type": "user",
                "role": role,
                "emailAddress": share_with_email
            }

            drive_service.permissions().create(
                fileId=doc_id,
                body=permission,
                sendNotificationEmail=False
            ).execute()

            logger.info(f"Shared document {doc_id} with {share_with_email} as {role}")

        except HttpError as e:
            logger.error(f"Failed to share document {doc_id}: {e}")
            raise


# Singleton instance
drive_service = GoogleDriveService()
