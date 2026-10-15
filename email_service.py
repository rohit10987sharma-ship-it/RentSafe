import os
import json
import smtplib
import random
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import Config

logger = logging.getLogger(__name__)

def get_smtp_config():
    """Retrieve active SMTP configuration from file or defaults."""
    if os.path.exists(Config.SMTP_CONFIG_FILE):
        try:
            with open(Config.SMTP_CONFIG_FILE, 'r') as f:
                data = json.load(f)
                return data
        except Exception as e:
            logger.error(f"Error reading SMTP config file: {e}")
    
    return {
        "smtp_server": Config.DEFAULT_SMTP_SERVER,
        "smtp_port": Config.DEFAULT_SMTP_PORT,
        "smtp_user": Config.DEFAULT_SMTP_USER,
        "smtp_pass": Config.DEFAULT_SMTP_PASS,
        "from_email": Config.DEFAULT_FROM_EMAIL,
        "use_tls": Config.DEFAULT_USE_TLS
    }

def save_smtp_config(server, port, user, password, from_email, use_tls=True):
    """Save SMTP configuration to json file."""
    config_data = {
        "smtp_server": server.strip(),
        "smtp_port": int(port),
        "smtp_user": user.strip(),
        "smtp_pass": password.strip(),
        "from_email": from_email.strip() or user.strip(),
        "use_tls": bool(use_tls)
    }
    with open(Config.SMTP_CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)
    return config_data

def generate_otp():
    """Generate a secure 6-digit numeric OTP."""
    return f"{random.randint(100000, 999999)}"

def send_real_email_otp(recipient_email, otp_code, purpose="Registration Verification"):
    """
    Sends a real OTP to the recipient's email address using SMTP.
    Never exposes the OTP in the response or on the user dashboard.
    """
    smtp_cfg = get_smtp_config()
    server_host = smtp_cfg.get("smtp_server")
    server_port = int(smtp_cfg.get("smtp_port", 587))
    username = smtp_cfg.get("smtp_user")
    password = smtp_cfg.get("smtp_pass")
    from_addr = smtp_cfg.get("from_email") or username

    subject = f"Your RentSafe Verification OTP: {otp_code} - Valid for 10 Minutes"
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px; color: #1e293b; }}
            .container {{ max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #2563eb, #1d4ed8); padding: 30px 24px; text-align: center; color: white; }}
            .header h1 {{ margin: 0; font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }}
            .header p {{ margin: 6px 0 0; opacity: 0.9; font-size: 14px; }}
            .content {{ padding: 32px 28px; }}
            .otp-box {{ background: #eff6ff; border: 2px dashed #3b82f6; border-radius: 8px; text-align: center; padding: 18px; margin: 24px 0; }}
            .otp-code {{ font-size: 36px; font-weight: 800; color: #1d4ed8; letter-spacing: 8px; margin: 0; font-family: monospace; }}
            .badge {{ display: inline-block; background: #dbeafe; color: #1e40af; padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; margin-bottom: 12px; }}
            .footer {{ background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px 28px; text-align: center; font-size: 12px; color: #64748b; }}
            .warning {{ font-size: 13px; color: #dc2626; margin-top: 18px; line-height: 1.5; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>RentSafe Portal</h1>
                <p>Secure Property Rental & Legal Verification System</p>
            </div>
            <div class="content">
                <span class="badge">{purpose}</span>
                <p>Hello,</p>
                <p>We received a request to verify your email address (<strong>{recipient_email}</strong>) on the <strong>RentSafe</strong> platform.</p>
                
                <div class="otp-box">
                    <div class="otp-code">{otp_code}</div>
                </div>
                
                <p style="text-align: center; font-size: 13px; color: #64748b; margin-top: -12px;">This one-time passcode is valid for <strong>10 minutes</strong>.</p>
                
                <div class="warning">
                    <strong>Security Notice:</strong> Please never share this OTP with anyone, including RentSafe agents or lawyers. Our support team will never ask for your verification code.
                </div>
            </div>
            <div class="footer">
                &copy; RentSafe Legal Rental Technologies &bull; If you did not request this, please disregard this email.
            </div>
        </div>
    </body>
    </html>
    """

    # Check if SMTP user/password are provided
    if not username or not password:
        logger.warning(f"SMTP credentials not fully configured. Storing OTP in memory/db. To send real emails, enter SMTP credentials in Admin settings or set SMTP_USER and SMTP_PASS.")
        # If in development without active SMTP credentials, we don't crash, but we return a clean status
        # Note: We do NOT send the OTP back to the client dashboard!
        return {
            "success": True,
            "dispatched": False,
            "warning": "SMTP server credentials not configured yet. Configure SMTP in Admin Dashboard > Email Settings to deliver live emails.",
            "message": f"Verification code generated for {recipient_email}. (SMTP not configured in Admin settings)."
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"RentSafe Support <{from_addr}>"
        msg["To"] = recipient_email

        # Attach HTML
        part = MIMEText(html_body, "html")
        msg.attach(part)

        # Connect to SMTP server
        if smtp_cfg.get("use_tls", True):
            server = smtplib.SMTP(server_host, server_port, timeout=12)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(server_host, server_port, timeout=12)
            server.ehlo()

        server.login(username, password)
        server.sendmail(from_addr, [recipient_email], msg.as_string())
        server.quit()

        logger.info(f"Real email OTP successfully delivered to {recipient_email}")
        return {
            "success": True,
            "dispatched": True,
            "message": f"Real OTP successfully dispatched to {recipient_email}. Please check your inbox or spam folder."
        }
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_email}: {str(e)}")
        return {
            "success": False,
            "dispatched": False,
            "error": f"SMTP Delivery Failed: {str(e)}"
        }

def test_smtp_connection(server, port, user, password, use_tls=True, test_recipient=None):
    """Test SMTP connection and optionally send a test verification email."""
    try:
        port = int(port)
        if use_tls:
            smtp_conn = smtplib.SMTP(server, port, timeout=10)
            smtp_conn.ehlo()
            smtp_conn.starttls()
            smtp_conn.ehlo()
        else:
            smtp_conn = smtplib.SMTP_SSL(server, port, timeout=10)
            smtp_conn.ehlo()
            
        smtp_conn.login(user, password)
        
        if test_recipient:
            test_msg = MIMEText("This is a RentSafe SMTP Test Email. Your mail server configuration is fully functional!")
            test_msg["Subject"] = "RentSafe SMTP Connection Test Successful"
            test_msg["From"] = user
            test_msg["To"] = test_recipient
            smtp_conn.sendmail(user, [test_recipient], test_msg.as_string())
            
        smtp_conn.quit()
        return {"success": True, "message": "SMTP Connection and Authentication succeeded!"}
    except Exception as e:
        return {"success": False, "error": str(e)}
