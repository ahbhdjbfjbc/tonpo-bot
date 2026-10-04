import logging

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
    logger.info("Starting Tonpo Bot v1.0.0")
    from bot.main import Bot
    bot = Bot()
    bot.run()


if __name__ == '__main__':
    main()
