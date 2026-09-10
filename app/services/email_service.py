import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import httpx
from app.config import get_settings


async def send_password_reset_email(to_email: str, reset_token: str) -> None:
    settings_obj = get_settings()
    reset_url = f"{settings_obj.APP_URL}/redefinir-senha?token={reset_token}"
    subject = "Redefinir senha - UniDANFE"

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;
                background: #111111; border-radius: 12px; color: #ffffff;">
        <h1 style="color: #22C55E; margin: 0 0 16px;">UniDANFE</h1>
        <p style="margin: 0 0 24px; color: #a1a1a1;">Recebemos um pedido para redefinir a senha da sua conta.</p>
        <a href="{reset_url}"
           style="display: inline-block; background: #22C55E; color: #000; padding: 12px 24px;
                  border-radius: 8px; text-decoration: none; font-weight: 600;">
            Redefinir senha
        </a>
        <p style="margin: 24px 0 0; font-size: 12px; color: #666666;">
            Se você não pediu isso, ignore este email. O link expira em 30 minutos.
        </p>
    </div>
    """
    await _send_email(to_email, subject, html)


async def send_welcome_email(to_email: str, name: str) -> None:
    settings_obj = get_settings()
    subject = "Bem-vindo ao UniDANFE!"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px;
                background: #111111; border-radius: 12px; color: #ffffff;">
        <h1 style="color: #22C55E; margin: 0 0 16px;">Bem-vindo, {name}!</h1>
        <p style="margin: 0 0 24px; color: #a1a1a1;">
            Sua conta foi criada com sucesso. Faça login e comece a processar seus DANFEs.
        </p>
        <a href="{settings_obj.APP_URL}/login"
           style="display: inline-block; background: #22C55E; color: #000; padding: 12px 24px;
                  border-radius: 8px; text-decoration: none; font-weight: 600;">
            Fazer login
        </a>
    </div>
    """
    await _send_email(to_email, subject, html)


async def _send_email(to_email: str, subject: str, html: str) -> None:
    settings_obj = get_settings()

    # 1) Resend (preferido)
    if settings_obj.RESEND_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings_obj.RESEND_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": settings_obj.EMAIL_FROM,
                        "to": [to_email],
                        "subject": subject,
                        "html": html,
                    },
                )
                if resp.status_code == 200:
                    return
        except Exception:
            # fallback para SMTP se Resend falhar
            pass

    # 2) SMTP (fallback)
    if settings_obj.SMTP_HOST:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings_obj.EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(settings_obj.SMTP_HOST, settings_obj.SMTP_PORT) as server:
            server.starttls()
            server.login(settings_obj.SMTP_USER, settings_obj.SMTP_PASSWORD)
            server.send_message(msg)