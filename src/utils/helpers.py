"""
Utility Functions and Helpers
"""

import json
from datetime import datetime, timezone
from typing import Optional, Tuple, Union
from pathlib import Path

import discord


# Standard footer for all embeds
def get_standard_footer() -> str:
    """Get standardized footer text with dynamic year"""
    current_year = datetime.now().year
    year_display = "2025" if current_year == 2025 else f"2025-{current_year}"
    return f"💎 NaveL for jji • {year_display}"


def create_embed(
    title: str = None,
    description: str = None,
    color: Union[int, discord.Color] = None,
    timestamp: datetime = None,
    footer_text: str = None,
    footer_icon: str = None,
    author_name: str = None,
    author_icon: str = None,
    author_url: str = None,
    thumbnail: str = None,
    image: str = None,
    fields: list = None,
    add_standard_footer: bool = True
) -> discord.Embed:
    """
    Create a standardized embed with automatic footer.
    
    Args:
        title: Embed title
        description: Embed description
        color: Embed color (int or discord.Color)
        timestamp: Timestamp for the embed
        footer_text: Custom footer text (appended to standard footer if add_standard_footer=True)
        footer_icon: Footer icon URL
        author_name: Author name
        author_icon: Author icon URL
        author_url: Author URL
        thumbnail: Thumbnail URL
        image: Image URL
        fields: List of dicts with 'name', 'value', and optional 'inline' keys
        add_standard_footer: Whether to add standard footer (default True)
    
    Returns:
        discord.Embed with standardized formatting
    """
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=timestamp
    )
    
    # Set footer
    if add_standard_footer:
        standard = get_standard_footer()
        if footer_text:
            final_footer = f"{footer_text} • {standard}"
        else:
            final_footer = standard
        embed.set_footer(text=final_footer, icon_url=footer_icon)
    elif footer_text:
        embed.set_footer(text=footer_text, icon_url=footer_icon)
    
    # Set author if provided
    if author_name:
        embed.set_author(name=author_name, icon_url=author_icon, url=author_url)
    
    # Set thumbnail if provided
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    
    # Set image if provided
    if image:
        embed.set_image(url=image)
    
    # Add fields if provided
    if fields:
        for field in fields:
            embed.add_field(
                name=field.get('name', '\u200b'),
                value=field.get('value', '\u200b'),
                inline=field.get('inline', False)
            )
    
    return embed


def load_config(path: str = "config.json") -> dict:
    """Load configuration from JSON file"""
    config_path = Path(path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict, path: str = "config.json") -> None:
    """Save configuration to JSON file"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def format_balance(amount: float) -> str:
    """Format balance with dollar sign - clean format without unnecessary decimals"""
    if amount == int(amount):
        return f"${int(amount)}"
    else:
        return f"${amount:.2f}"


def format_time(seconds: int) -> str:
    """Format seconds into human-readable time"""
    if seconds < 60:
        return f"{seconds}s"
    
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m {seconds % 60}s"
    
    hours = minutes // 60
    remaining_minutes = minutes % 60
    
    if hours < 24:
        return f"{hours}h {remaining_minutes}m"
    
    days = hours // 24
    remaining_hours = hours % 24
    
    return f"{days}d {remaining_hours}h {remaining_minutes}m"


def format_sqb_time(seconds: int) -> str:
    """Format SQB (Squadron Battles) time with full labels"""
    if seconds == 0:
        return "0 hours"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    
    return " ".join(parts) if parts else "< 1 minute"


def is_prime_time(
    start_hour: int = 14, 
    end_hour: int = 22, 
    tz: timezone = timezone.utc
) -> bool:
    """Check if current time is within prime time hours"""
    now = datetime.now(tz)
    return start_hour <= now.hour < end_hour


def get_prime_time_info(
    start_hour: int = 14,
    end_hour: int = 22,
    tz: timezone = timezone.utc
) -> Tuple[bool, Optional[int]]:
    """
    Get prime time status and seconds until next state change.
    Returns (is_prime_time, seconds_until_change)
    """
    now = datetime.now(tz)
    current_hour = now.hour
    current_minute = now.minute
    current_second = now.second
    
    is_prime = start_hour <= current_hour < end_hour
    
    if is_prime:
        # Seconds until end of prime time
        hours_until_end = end_hour - current_hour - 1
        minutes_until_end = 59 - current_minute
        seconds_until_end = 60 - current_second
        total_seconds = hours_until_end * 3600 + minutes_until_end * 60 + seconds_until_end
    else:
        if current_hour >= end_hour:
            # After prime time, calculate until next day's start
            hours_until_start = (24 - current_hour) + start_hour - 1
        else:
            # Before prime time
            hours_until_start = start_hour - current_hour - 1
        
        minutes_until_start = 59 - current_minute
        seconds_until_start = 60 - current_second
        total_seconds = hours_until_start * 3600 + minutes_until_start * 60 + seconds_until_start
    
    return is_prime, total_seconds


def calculate_tax(amount: float, tax_rate: float) -> Tuple[float, float]:
    """
    Calculate tax on an amount.
    Returns (net_amount, tax_amount)
    """
    tax_amount = amount * (tax_rate / 100)
    net_amount = amount - tax_amount
    return net_amount, tax_amount


def validate_bet(
    amount: float,
    balance: float,
    min_bet: float = 1,
    max_bet: float = 10000,
    max_percentage: float = 100
) -> Tuple[bool, str]:
    """
    Validate a bet amount.
    Returns (is_valid, error_message)
    """
    if amount < min_bet:
        return False, f"Minimum bet is {format_balance(min_bet)}"
    
    if amount > max_bet:
        return False, f"Maximum bet is {format_balance(max_bet)}"
    
    max_allowed = balance * (max_percentage / 100)
    if amount > max_allowed:
        return False, f"Maximum bet is {max_percentage}% of your balance ({format_balance(max_allowed)})"
    
    if amount > balance:
        return False, f"Insufficient balance. You have {format_balance(balance)}"
    
    return True, ""


def get_rank_emoji(position: int) -> str:
    """Get emoji for leaderboard position"""
    if position == 1:
        return "🥇"
    elif position == 2:
        return "🥈"
    elif position == 3:
        return "🥉"
    else:
        return f"`#{position}`"


def truncate_string(s: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate a string to max length with suffix"""
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def parse_color_hex(color: str) -> Optional[int]:
    """Parse color hex string to integer"""
    color = color.strip().lstrip("#")
    
    if len(color) not in (3, 6):
        return None
    
    try:
        if len(color) == 3:
            color = "".join(c * 2 for c in color)
        return int(color, 16)
    except ValueError:
        return None


def color_int_to_hex(color: int) -> str:
    """Convert color integer to hex string"""
    return f"#{color:06x}"


# Card game utilities
CARD_SUITS = ["♠", "♥", "♦", "♣"]
CARD_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

CARD_VALUES = {
    "A": 11,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 10,
    "Q": 10,
    "K": 10,
}


def card_to_emoji(rank: str, suit: str) -> str:
    """Convert card to display string"""
    suit_colors = {"♠": "🖤", "♥": "❤️", "♦": "💎", "♣": "🍀"}
    return f"{rank}{suit}"


def format_hand(cards: list) -> str:
    """Format a hand of cards for display"""
    return " ".join(f"[{card_to_emoji(c['rank'], c['suit'])}]" for c in cards)


def calculate_hand_value(cards: list) -> int:
    """Calculate blackjack hand value"""
    value = 0
    aces = 0
    
    for card in cards:
        rank = card["rank"]
        if rank == "A":
            aces += 1
            value += 11
        else:
            value += CARD_VALUES[rank]
    
    # Adjust for aces
    while value > 21 and aces > 0:
        value -= 10
        aces -= 1
    
    return value


def is_soft_hand(cards: list) -> bool:
    """Check if hand is soft (has ace counted as 11)"""
    value = 0
    aces = 0
    
    for card in cards:
        rank = card["rank"]
        if rank == "A":
            aces += 1
            value += 11
        else:
            value += CARD_VALUES[rank]
    
    # If we have an ace and value is still <= 21, it's soft
    return aces > 0 and value <= 21


def is_blackjack(cards: list) -> bool:
    """Check if hand is a natural blackjack"""
    if len(cards) != 2:
        return False
    
    ranks = [c["rank"] for c in cards]
    has_ace = "A" in ranks
    has_ten = any(r in ["10", "J", "Q", "K"] for r in ranks)
    
    return has_ace and has_ten


def can_split(cards: list) -> bool:
    """Check if hand can be split"""
    if len(cards) != 2:
        return False
    
    return cards[0]["rank"] == cards[1]["rank"]


def can_double(cards: list) -> bool:
    """Check if hand can be doubled down"""
    return len(cards) == 2
