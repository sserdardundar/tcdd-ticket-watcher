import requests
import logging
from common.config import settings

logger = logging.getLogger(__name__)

def send_telegram(message: str, chat_id: str = None, reply_markup: dict = None):
    """Send a Telegram notification message."""
    token = settings.TELEGRAM_BOT_TOKEN
    target_chat = chat_id or settings.TELEGRAM_CHAT_ID
    
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Notification skipped.")
        return False
    
    if not target_chat:
        logger.error(f"Telegram chat_id missing (provided: {chat_id}, default: {settings.TELEGRAM_CHAT_ID}). Notification skipped.")
        return False
    
    # Validate chat_id is not 0 or invalid
    try:
        chat_id_int = int(target_chat)
        if chat_id_int <= 0:
            logger.error(f"Invalid chat_id: {target_chat}. Must be a positive integer.")
            return False
    except (ValueError, TypeError):
        logger.error(f"Invalid chat_id format: {target_chat}. Must be a number.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        logger.info(f"Sending Telegram notification to chat_id: {target_chat}")
        response = requests.post(url, json=payload, timeout=20)
        
        # Get response details for debugging
        try:
            result = response.json()
        except:
            result = {"ok": False, "description": f"HTTP {response.status_code}"}
        
        if response.status_code == 200 and result.get("ok"):
            logger.info(f"Successfully sent Telegram notification to chat_id: {target_chat}")
            return True
        else:
            error_desc = result.get("description", f"HTTP {response.status_code}")
            error_code = result.get("error_code", response.status_code)
            logger.error(f"Telegram API error ({error_code}): {error_desc} (chat_id: {target_chat})")
            logger.debug(f"Request payload: {payload}")
            logger.debug(f"Response: {result}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to send telegram message to {target_chat}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending telegram message to {target_chat}: {e}", exc_info=True)
        return False
