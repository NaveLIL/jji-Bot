"""
Games Package
"""

from src.games.blackjack import (
    BlackjackGame,
    GameState,
    HandResult,
    Card,
    Hand,
    Shoe,
    create_blackjack_game,
)

from src.games.coinflip import (
    CoinflipGame,
    CoinSide,
    CoinflipResult,
    create_coinflip_game,
    animated_flip,
)

__all__ = [
    # Blackjack
    "BlackjackGame",
    "GameState",
    "HandResult",
    "Card",
    "Hand",
    "Shoe",
    "create_blackjack_game",
    # Coinflip
    "CoinflipGame",
    "CoinSide",
    "CoinflipResult",
    "create_coinflip_game",
    "animated_flip",
]
