"""
Utilities Package
"""

from src.utils.helpers import (
    load_config,
    save_config,
    format_balance,
    format_time,
    format_sqb_time,
    is_prime_time,
    get_prime_time_info,
    calculate_tax,
    validate_bet,
    get_rank_emoji,
    truncate_string,
    parse_color_hex,
    color_int_to_hex,
    CARD_SUITS,
    CARD_RANKS,
    CARD_VALUES,
    card_to_emoji,
    format_hand,
    calculate_hand_value,
    is_soft_hand,
    is_blackjack,
    can_split,
    can_double,
    get_standard_footer,
    create_embed,
)

from src.utils.logger import (
    setup_logging,
    get_logger,
    DiscordLogger,
)

from src.utils.metrics import (
    BotMetrics,
    metrics,
)

from src.utils.security import (
    RateLimitExceeded,
    UserBlacklisted,
    check_rate_limit,
    check_user_allowed,
    rate_limited,
    game_rate_limited,
    check_suspicious_activity,
    handle_exploit_attempt,
    admin_only,
    officer_only,
)

__all__ = [
    # Helpers
    "load_config",
    "save_config",
    "format_balance",
    "format_time",
    "format_sqb_time",
    "is_prime_time",
    "get_prime_time_info",
    "calculate_tax",
    "validate_bet",
    "get_rank_emoji",
    "truncate_string",
    "parse_color_hex",
    "color_int_to_hex",
    "CARD_SUITS",
    "CARD_RANKS",
    "CARD_VALUES",
    "card_to_emoji",
    "format_hand",
    "calculate_hand_value",
    "is_soft_hand",
    "is_blackjack",
    "can_split",
    "can_double",
    # Logger
    "setup_logging",
    "get_logger",
    "DiscordLogger",
    # Metrics
    "BotMetrics",
    "metrics",
    # Security
    "RateLimitExceeded",
    "UserBlacklisted",
    "check_rate_limit",
    "check_user_allowed",
    "rate_limited",
    "game_rate_limited",
    "check_suspicious_activity",
    "handle_exploit_attempt",
    "admin_only",
    "officer_only",
]
