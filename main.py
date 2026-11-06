import logging
import sys

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
# HTTPX request logs include full Telegram API URLs, which contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def main():
    """Console entry point declared by the project's package metadata."""
    from utils.log_redaction import configured_secrets, install_secret_redaction

    install_secret_redaction(configured_secrets())
    logger.info("Starting Tonpo Bot v1.0.0")

    from telegram.error import InvalidToken
    from bot.main import Bot

    try:
        bot = Bot()
        bot.run()
    except InvalidToken:
        logger.critical("Telegram rejected BOT_TOKEN. Check the token from @BotFather and restart.")
        sys.exit(2)


if __name__ == '__main__':
    main()
