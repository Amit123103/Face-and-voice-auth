"""
Email Notification Service
Handles sending transactional emails (welcome, alerts) asynchronously.
"""

import logging
import smtplib
from email.message import EmailMessage
from backend.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailService:
    def __init__(self):
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASSWORD
        self.is_configured = bool(self.host and self.user and self.password)

    def send_email(self, to_email: str, subject: str, body: str, html_content: str = None):
        """Send an email using SMTP. Fallback to console logging if unconfigured."""
        if not self.is_configured:
            logger.info("=== MOCK EMAIL ===")
            logger.info(f"To: {to_email}")
            logger.info(f"Subject: {subject}")
            logger.info(f"Body: {body}")
            if html_content:
                logger.debug(f"HTML: {html_content[:100]}...")
            logger.info("==================")
            return

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = self.user or "noreply@facevoiceauth.local"
        msg['To'] = to_email
        msg.set_content(body)

        if html_content:
            msg.add_alternative(html_content, subtype='html')

        try:
            with smtplib.SMTP(self.host, self.port) as server:
                if self.port == 587:
                    server.starttls()
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.send_message(msg)
                logger.info(f"Email sent successfully to {to_email}")
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")

    def _get_html_template(self, title: str, content: str, action_text: str = None, action_url: str = None):
        """Generate a consistent premium HTML template for emails."""
        action_btn = (
            f'<a href="{action_url}" style="display: inline-block; padding: 12px 24px; '
            'background-color: #0d9488; color: white; text-decoration: none; border-radius: 8px; '
            f'font-weight: bold; margin-top: 20px;">{action_text}</a>'
            if action_text else ''
        )

        return f"""
        <html>
        <body style="font-family: sans-serif; color: #1f2937; line-height: 1.6; margin: 0; padding: 0;">
            <div style="background-color: #f3f4f6; padding: 40px 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);">
                    <div style="background: linear-gradient(135deg, #0d9488 0%, #0891b2 100%); padding: 30px; text-align: center; color: white;">
                        <h1 style="margin: 0; font-size: 24px;">🛡️ FaceVoiceAuth</h1>
                    </div>
                    <div style="padding: 40px;">
                        <h2 style="margin-top: 0; color: #111827;">{title}</h2>
                        <div style="color: #4b5563;">{content}</div>
                        {action_btn}
                        <hr style="margin-top: 40px; border: 0; border-top: 1px solid #e5e7eb;">
                        <p style="font-size: 12px; color: #9ca3af; text-align: center;">
                            If you did not expect this notification, please secure your account immediately.
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

    def send_welcome_email(self, to_email: str, name: str):
        subject = "Welcome to FaceVoiceAuth Payment System!"
        content = (
            f"Hello {name}, your account has been successfully created. "
            "You have been credited with a starting balance of $1000.00 to try out the network."
        )
        html = self._get_html_template(
            "Welcome aboard!",
            content,
            "Go to Dashboard",
            "http://localhost:8000/dashboard.html"
        )
        self.send_email(to_email, subject, content, html)

    def send_security_alert(self, to_email: str, event_name: str, detail: str):
        """Send a high-priority security alert."""
        subject = f"Security Alert: {event_name}"
        content = f"We detected a critical event on your account:<br><br><b>{event_name}</b><br>{detail}"
        html = self._get_html_template(
            "Security Notification",
            content,
            "Secure Account",
            "http://localhost:8000/dashboard.html"
        )
        self.send_email(to_email, subject, content, html)

    def send_login_alert(self, to_email: str, ip: str, method: str):
        self.send_security_alert(to_email, "New Login Detected", f"Method: {method}<br>IP Address: {ip}")

    def send_failed_login_alert(self, to_email: str, ip: str, method: str):
        self.send_security_alert(to_email, "Failed Login Attempt", f"Unauthorized access attempt blocked.<br>Method: {method}<br>IP Address: {ip}")

email_service = EmailService()
