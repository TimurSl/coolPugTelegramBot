import logging


class StringUtils:
    """String manipulation utilities"""

    @staticmethod
    def extract_username(text: str) -> str:
        """Extract username from command text"""
        parts = text.split()
        username = parts[1] if len(parts) > 1 else "unknown"
        logging.debug("Extracted username '%s' from text='%s'", username, text)
        return username

    @staticmethod
    def format_joke(joke: str) -> str:
        """Format joke with emojis"""
        formatted = f"😄 {joke} 😄"
        logging.debug("Formatted joke: %s", formatted)
        return formatted

    @staticmethod
    def truncate_text(text: str, max_length: int = 100) -> str:
        """Truncate text to specified length"""
        truncated = text[:max_length] + "..." if len(text) > max_length else text
        logging.debug("Truncated text to '%s' (max_length=%s)", truncated, max_length)
        return truncated

