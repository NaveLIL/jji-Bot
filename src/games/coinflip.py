"""
Coinflip Game Engine
With edge case and animations
"""

import random
import asyncio
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum


class CoinSide(str, Enum):
    """Coin sides"""
    HEADS = "heads"
    TAILS = "tails"
    EDGE = "edge"  # Rare edge case


class CoinflipResult(str, Enum):
    """Coinflip outcomes"""
    WIN = "win"
    LOSE = "lose"
    EDGE = "edge"  # 0.5% chance - auto loss


@dataclass
class CoinflipGame:
    """Coinflip game state"""
    user_id: int
    bet: float
    chosen_side: CoinSide
    result_side: Optional[CoinSide] = None
    outcome: Optional[CoinflipResult] = None
    winnings: float = 0.0
    is_complete: bool = False
    
    # Animation frames
    SPIN_FRAMES = [
        "🪙 *spinning...*",
        "🔄 *spinning...*",
        "💫 *spinning...*",
        "✨ *spinning...*",
        "🎲 *spinning...*",
        "🪙 *spinning...*",
    ]
    
    # Result displays
    SIDE_EMOJIS = {
        CoinSide.HEADS: "🪙 **HEADS**",
        CoinSide.TAILS: "🔴 **TAILS**",
        CoinSide.EDGE: "⚡ **EDGE!**"
    }
    
    def flip(self, edge_chance: float = 0.5) -> CoinflipResult:
        """
        Flip the coin and determine result.
        edge_chance is percentage (0.5 = 0.5%)
        """
        # Check for edge case first
        edge_roll = random.uniform(0, 100)
        
        if edge_roll < edge_chance:
            # Edge case - automatic loss
            self.result_side = CoinSide.EDGE
            self.outcome = CoinflipResult.EDGE
            self.winnings = -self.bet
        else:
            # Normal flip
            self.result_side = random.choice([CoinSide.HEADS, CoinSide.TAILS])
            
            if self.result_side == self.chosen_side:
                self.outcome = CoinflipResult.WIN
                self.winnings = self.bet  # Win equals bet (1:1)
            else:
                self.outcome = CoinflipResult.LOSE
                self.winnings = -self.bet
        
        self.is_complete = True
        return self.outcome
    
    def get_result_display(self) -> str:
        """Get display string for result"""
        if not self.is_complete:
            return "Game in progress..."
        
        emoji = self.SIDE_EMOJIS.get(self.result_side, "❓")
        
        if self.outcome == CoinflipResult.WIN:
            return f"{emoji}\n\n🎉 **You WIN!** +${self.winnings:,.2f}"
        elif self.outcome == CoinflipResult.EDGE:
            return f"{emoji}\n\n💀 **The coin landed on its EDGE!**\nThis is incredibly rare... but you lose! -${abs(self.winnings):,.2f}"
        else:
            return f"{emoji}\n\n💔 **You lose!** -${abs(self.winnings):,.2f}"
    
    def get_spin_frame(self, index: int) -> str:
        """Get animation frame at index"""
        return self.SPIN_FRAMES[index % len(self.SPIN_FRAMES)]
    
    def to_dict(self) -> dict:
        """Serialize to dictionary"""
        return {
            "user_id": self.user_id,
            "bet": self.bet,
            "chosen_side": self.chosen_side.value,
            "result_side": self.result_side.value if self.result_side else None,
            "outcome": self.outcome.value if self.outcome else None,
            "winnings": self.winnings,
            "is_complete": self.is_complete
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CoinflipGame":
        """Deserialize from dictionary"""
        game = cls(
            user_id=data["user_id"],
            bet=data["bet"],
            chosen_side=CoinSide(data["chosen_side"])
        )
        if data.get("result_side"):
            game.result_side = CoinSide(data["result_side"])
        if data.get("outcome"):
            game.outcome = CoinflipResult(data["outcome"])
        game.winnings = data.get("winnings", 0.0)
        game.is_complete = data.get("is_complete", False)
        return game


async def animated_flip(
    game: CoinflipGame,
    message,
    edge_chance: float = 0.5,
    animation_duration: float = 3.0
) -> CoinflipResult:
    """
    Run coinflip with animated message updates.
    Returns the result after animation.
    """
    import discord
    
    # Calculate frames
    frame_count = int(animation_duration / 0.5)
    
    for i in range(frame_count):
        embed = discord.Embed(
            title="🪙 Coinflip",
            description=game.get_spin_frame(i),
            color=discord.Color.gold()
        )
        embed.add_field(name="Your Choice", value=game.chosen_side.value.upper(), inline=True)
        embed.add_field(name="Bet", value=f"${game.bet:,.2f}", inline=True)
        
        try:
            await message.edit(embed=embed)
        except Exception:
            pass
        
        await asyncio.sleep(0.5)
    
    # Flip and show result
    result = game.flip(edge_chance)
    
    # Result colors
    if result == CoinflipResult.WIN:
        color = discord.Color.green()
    elif result == CoinflipResult.EDGE:
        color = discord.Color.purple()
    else:
        color = discord.Color.red()
    
    embed = discord.Embed(
        title="🪙 Coinflip - Result!",
        description=game.get_result_display(),
        color=color
    )
    embed.add_field(name="Your Choice", value=game.chosen_side.value.upper(), inline=True)
    embed.add_field(name="Bet", value=f"${game.bet:,.2f}", inline=True)
    
    try:
        await message.edit(embed=embed)
    except Exception:
        pass
    
    return result


def create_coinflip_game(
    user_id: int,
    bet: float,
    side: str
) -> Tuple[CoinflipGame, Optional[str]]:
    """
    Create a new coinflip game.
    Returns (game, error_message)
    """
    # Validate side
    side_lower = side.lower()
    
    if side_lower in ["heads", "h", "head", "орёл", "орел"]:
        chosen_side = CoinSide.HEADS
    elif side_lower in ["tails", "t", "tail", "решка"]:
        chosen_side = CoinSide.TAILS
    else:
        return None, "Invalid side! Choose 'heads' or 'tails'."
    
    game = CoinflipGame(
        user_id=user_id,
        bet=bet,
        chosen_side=chosen_side
    )
    
    return game, None
