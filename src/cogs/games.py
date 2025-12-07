"""
Games Cog - Enhanced Blackjack and Coinflip with PvP
Beautiful card visuals, Play Again feature, and competitive PvP mode
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal, Optional, Dict
from datetime import datetime, timezone
import random

from src.services.database import db
from src.services.cache import cache
from src.models.database import TransactionType, GameType
from src.games.blackjack import create_blackjack_game, BlackjackGame, GameState
from src.games.coinflip import create_coinflip_game, CoinflipResult, CoinSide
from src.utils.helpers import format_balance, validate_bet, calculate_tax, load_config
from src.utils.security import rate_limited, game_rate_limited
from src.utils.metrics import metrics


# ═══════════════════════════════════════════════════════════════════════════════
# CARD VISUALS - Beautiful card display
# ═══════════════════════════════════════════════════════════════════════════════

def get_fancy_card_display(cards: list, hide_first: bool = False) -> str:
    """Generate fancy card display with emojis
    
    Cards are in format like "A♠", "10♥", "K♦"
    """
    if not cards:
        return "```\n  Empty  \n```"
    
    result = []
    for i, card in enumerate(cards):
        if i == 0 and hide_first:
            result.append("🂠")
        else:
            # Parse card string - last character is suit
            suit = card[-1]
            rank = card[:-1]
            
            # Use colored emoji hearts/diamonds for red, black for spades/clubs
            if suit == "♥":
                result.append(f"**{rank}**❤️")
            elif suit == "♦":
                result.append(f"**{rank}**♦️")
            elif suit == "♠":
                result.append(f"**{rank}**♠️")
            elif suit == "♣":
                result.append(f"**{rank}**♣️")
            else:
                result.append(f"**{rank}**{suit}")
    
    return " │ ".join(result)


# ═══════════════════════════════════════════════════════════════════════════════
# PVP MATCHMAKING SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

class PvPQueue:
    """Manages PvP matchmaking queue"""
    
    def __init__(self):
        self.waiting: Dict[int, dict] = {}
        self.active_games: Dict[str, "PvPBlackjackGame"] = {}
    
    def add_to_queue(self, user_id: int, bet: float, interaction: discord.Interaction) -> Optional[tuple]:
        """Add player to queue. Returns matched opponent info if found."""
        if user_id in self.waiting:
            return None
        
        # Look for opponent with similar bet (within 20%)
        for opponent_id, data in list(self.waiting.items()):
            bet_diff = abs(data["bet"] - bet) / max(data["bet"], bet)
            if bet_diff <= 0.2:
                opponent_data = self.waiting.pop(opponent_id)
                return (opponent_id, opponent_data)
        
        self.waiting[user_id] = {
            "bet": bet,
            "timestamp": datetime.now(timezone.utc),
            "interaction": interaction
        }
        return None
    
    def remove_from_queue(self, user_id: int):
        if user_id in self.waiting:
            del self.waiting[user_id]
    
    def get_queue_size(self) -> int:
        return len(self.waiting)


pvp_queue = PvPQueue()


class PvPPlayerHand:
    """Simple hand for PvP blackjack (no dealer)"""
    
    def __init__(self, user_id: int, bet: float):
        self.user_id = user_id
        self.bet = bet
        self.cards: list = []
        self.is_done = False
        self.is_doubled = False
        
        # Card constants
        self.suits = ["♠", "♥", "♦", "♣"]
        self.ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
        
        # Create a mini deck for this player
        self.deck = []
        for suit in self.suits:
            for rank in self.ranks:
                self.deck.append(f"{rank}{suit}")
        random.shuffle(self.deck)
        
        # Deal initial 2 cards
        self.cards.append(self.deck.pop())
        self.cards.append(self.deck.pop())
    
    @property
    def value(self) -> int:
        """Calculate hand value"""
        total = 0
        aces = 0
        for card in self.cards:
            rank = card[:-1]
            if rank == "A":
                aces += 1
                total += 11
            elif rank in ["K", "Q", "J"]:
                total += 10
            else:
                total += int(rank)
        
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        return total
    
    @property
    def is_bust(self) -> bool:
        return self.value > 21
    
    @property
    def is_blackjack(self) -> bool:
        return len(self.cards) == 2 and self.value == 21
    
    def hit(self):
        """Draw a card"""
        if not self.is_done and not self.is_bust:
            self.cards.append(self.deck.pop())
            if self.is_bust:
                self.is_done = True
    
    def stand(self):
        """Stand"""
        self.is_done = True
    
    def double_down(self):
        """Double down - one more card and done"""
        if len(self.cards) == 2 and not self.is_done:
            self.is_doubled = True
            self.bet *= 2
            self.cards.append(self.deck.pop())
            self.is_done = True


class PvPBlackjackGame:
    """PvP Blackjack game between two players"""
    
    def __init__(self, player1_id: int, player2_id: int, bet: float):
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.bet = bet
        self.pot = bet * 2
        
        # Create simple PvP hands instead of full games
        self.hand1 = PvPPlayerHand(player1_id, bet)
        self.hand2 = PvPPlayerHand(player2_id, bet)
        
        self.winner: Optional[int] = None
        self.is_complete = False
    
    def get_player_hand(self, user_id: int) -> Optional[PvPPlayerHand]:
        if user_id == self.player1_id:
            return self.hand1
        elif user_id == self.player2_id:
            return self.hand2
        return None
    
    def check_complete(self):
        """Check if both players are done"""
        if self.hand1.is_done and self.hand2.is_done:
            self._determine_winner()
    
    def mark_player_done(self, user_id: int):
        hand = self.get_player_hand(user_id)
        if hand:
            hand.is_done = True
            self.check_complete()
    
    def _determine_winner(self):
        self.is_complete = True
        
        # Get scores (bust = 0)
        score1 = self.hand1.value if not self.hand1.is_bust else 0
        score2 = self.hand2.value if not self.hand2.is_bust else 0
        
        # Blackjack beats 21 from multiple cards
        bj1 = self.hand1.is_blackjack
        bj2 = self.hand2.is_blackjack
        
        if bj1 and not bj2:
            self.winner = self.player1_id
        elif bj2 and not bj1:
            self.winner = self.player2_id
        elif score1 > score2:
            self.winner = self.player1_id
        elif score2 > score1:
            self.winner = self.player2_id
        else:
            self.winner = None  # Tie


# ═══════════════════════════════════════════════════════════════════════════════
# ENHANCED BLACKJACK VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class EnhancedBlackjackView(discord.ui.View):
    """Beautiful interactive blackjack game view with Play Again"""
    
    def __init__(self, game: BlackjackGame, cog: "GamesCog", bet: float, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.game = game
        self.cog = cog
        self.bet = bet
        self.message: discord.Message = None
        self.update_buttons()
    
    def update_buttons(self):
        """Update button availability based on game state"""
        self.clear_items()
        
        if self.game.is_complete:
            self.add_item(PlayAgainButton(self.bet))
            self.add_item(DoubleOrNothingButton(self.bet))
            self.add_item(QuitButton())
            return
        
        actions = self.game.get_available_actions()
        
        if "insurance_yes" in actions:
            self.add_item(InsuranceYesButton())
            self.add_item(InsuranceNoButton())
            return
        
        if "hit" in actions:
            self.add_item(HitButton())
        if "stand" in actions:
            self.add_item(StandButton())
        if "double" in actions:
            self.add_item(DoubleButton())
        if "split" in actions:
            self.add_item(SplitButton())
        if "surrender" in actions:
            self.add_item(SurrenderButton())
    
    def get_embed(self) -> discord.Embed:
        """Generate beautiful game embed"""
        data = self.game.get_display_embed_data()
        
        if self.game.is_complete:
            net = data["net_result"]
            if net > 0:
                color = 0x00FF00
                status = "🎉 YOU WIN!"
            elif net < 0:
                color = 0xFF0000
                status = "💔 YOU LOSE"
            else:
                color = 0xFFD700
                status = "🤝 PUSH"
        else:
            color = 0x2F3136
            status = "🎰 YOUR TURN"
        
        embed = discord.Embed(title="🃏 BLACKJACK", color=color)
        embed.description = f"```ansi\n\u001b[1;33m{status}\u001b[0m\n```"
        
        # DEALER
        dealer_cards = data.get("dealer_cards_list", [])
        dealer_value = data["dealer_value"]
        
        if self.game.is_complete:
            dealer_display = get_fancy_card_display(dealer_cards, hide_first=False)
            dealer_header = f"🎩 DEALER — **{dealer_value}**"
        else:
            dealer_display = get_fancy_card_display(dealer_cards, hide_first=True)
            dealer_header = "🎩 DEALER — **?**"
        
        embed.add_field(
            name=dealer_header,
            value=f"╔══════════════════════════╗\n{dealer_display}\n╚══════════════════════════╝",
            inline=False
        )
        
        # PLAYER
        for i, hand in enumerate(data["player_hands"]):
            player_cards = hand.get("cards_list", [])
            hand_value_str = hand["value"]  # Display string like "21", "21 (soft)", "BUST"
            numeric_value = hand.get("value_numeric", 0)  # Numeric value for comparisons
            is_bust = hand.get("is_bust", False)
            is_blackjack = hand.get("is_blackjack", False)
            is_current = hand.get("is_current", False)
            hand_bet = hand.get("bet_amount", self.bet)  # Numeric bet amount
            
            if is_bust:
                status_icon = "💥 BUST"
                value_display = f"~~{numeric_value}~~"
            elif is_blackjack:
                status_icon = "🎰 BLACKJACK!"
                value_display = f"**{hand_value_str}**"
            elif numeric_value == 21:
                status_icon = "✨ 21!"
                value_display = f"**{hand_value_str}**"
            else:
                status_icon = ""
                value_display = f"**{hand_value_str}**"
            
            pointer = "➤ " if is_current and not self.game.is_complete else ""
            hand_label = f"Hand #{i+1}" if len(data["player_hands"]) > 1 else "YOUR HAND"
            
            player_display = get_fancy_card_display(player_cards)
            
            embed.add_field(
                name=f"{pointer}🎯 {hand_label} — {value_display} {status_icon}",
                value=f"╔══════════════════════════╗\n{player_display}\n╚══════════════════════════╝\n💰 Bet: **{format_balance(hand_bet)}**",
                inline=True
            )
        
        # RESULTS
        if self.game.is_complete and data.get("results"):
            results_lines = []
            for i, (result, amount) in enumerate(data["results"]):
                prefix = f"Hand #{i+1}: " if len(data["results"]) > 1 else ""
                if amount > 0:
                    results_lines.append(f"✅ {prefix}{result.upper()} — **+{format_balance(amount)}**")
                elif amount < 0:
                    results_lines.append(f"❌ {prefix}{result.upper()} — **{format_balance(amount)}**")
                else:
                    results_lines.append(f"🤝 {prefix}{result.upper()} — **$0.00**")
            
            embed.add_field(name="📊 RESULTS", value="\n".join(results_lines), inline=False)
            
            net = data["net_result"]
            if net > 0:
                embed.add_field(name="💎 NET PROFIT", value=f"```diff\n+ {format_balance(net)}\n```", inline=True)
            elif net < 0:
                embed.add_field(name="📉 NET LOSS", value=f"```diff\n- {format_balance(abs(net))}\n```", inline=True)
            else:
                embed.add_field(name="⚖️ BREAK EVEN", value="```\n$0.00\n```", inline=True)
        
        if not self.game.is_complete:
            tips = [
                "💡 Stand on 17+ against dealer 2-6",
                "💡 Hit on 16 or less against dealer 7+",
                "💡 Always split Aces and 8s",
                "💡 Never split 10s or 5s",
                "💡 Double on 11 against dealer 2-10"
            ]
            embed.set_footer(text=random.choice(tips) + " • Developed by NaveL for JJI in 2025")
        else:
            embed.set_footer(text="🎰 Press 'Play Again' for another round! • Developed by NaveL for JJI in 2025")
        
        return embed
    
    async def on_timeout(self):
        if not self.game.is_complete:
            while not self.game.is_complete:
                self.game.stand()
            await self.finish_game()
    
    async def finish_game(self):
        net_result = self.game.get_net_result()
        
        if net_result != 0:
            if net_result > 0:
                # Player wins - calculate tax only on PROFIT, not on bet return
                profit_amount = net_result  # This is just the profit
                
                economy = await db.get_server_economy()
                net_profit, tax = calculate_tax(profit_amount, economy.tax_rate)
                
                # Total payout = bet back + net profit after tax
                total_payout = self.bet + net_profit
                
                # Deduct total payout from server budget
                await db.update_server_budget(-total_payout)
                
                # Give player their winnings (no additional tax deduction)
                await db.update_user_balance(
                    self.game.user_id,
                    total_payout,
                    TransactionType.GAME_WIN,
                    description="Blackjack win"
                )
                
                if tax > 0:
                    await db.add_taxes_collected(tax)
                    metrics.track_tax(tax)
                
                metrics.track_game("blackjack", "win", self.bet)
            else:
                # Player loses - money stays in server budget (already added when bet placed)
                metrics.track_game("blackjack", "lose", self.bet)
        else:
            # Push - refund bet from server budget (no tax on refund)
            await db.update_server_budget(-self.bet)
            await db.update_user_balance(
                self.game.user_id,
                self.bet,
                TransactionType.GAME_WIN,
                description="Blackjack push - refund"
            )
            metrics.track_game("blackjack", "push", self.bet)
        
        await cache.delete_game_state(self.game.user_id, "blackjack")
        self.update_buttons()
    
    async def update_game(self, interaction: discord.Interaction):
        if self.game.is_complete:
            await self.finish_game()
        else:
            await cache.save_game_state(self.game.user_id, "blackjack", self.game.to_dict())
        
        self.update_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


# ═══════════════════════════════════════════════════════════════════════════════
# GAME BUTTONS
# ═══════════════════════════════════════════════════════════════════════════════

class HitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="HIT", style=discord.ButtonStyle.primary, emoji="🎴", custom_id="bj:hit")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        view.game.hit()
        await view.update_game(interaction)


class StandButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="STAND", style=discord.ButtonStyle.secondary, emoji="🛑", custom_id="bj:stand")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        view.game.stand()
        await view.update_game(interaction)


class DoubleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="DOUBLE", style=discord.ButtonStyle.success, emoji="💰", custom_id="bj:double")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        user = await db.get_or_create_user(view.game.user_id)
        double_cost = view.game.current_hand.bet
        
        if user.balance < double_cost:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(double_cost)}** to double.",
                ephemeral=True
            )
            return
        
        await db.update_user_balance(view.game.user_id, -double_cost, TransactionType.GAME_LOSS, description="Blackjack double down")
        view.game.double_down()
        await view.update_game(interaction)


class SplitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="SPLIT", style=discord.ButtonStyle.success, emoji="✂️", custom_id="bj:split")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        user = await db.get_or_create_user(view.game.user_id)
        split_cost = view.game.current_hand.bet
        
        if user.balance < split_cost:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(split_cost)}** to split.",
                ephemeral=True
            )
            return
        
        await db.update_user_balance(view.game.user_id, -split_cost, TransactionType.GAME_LOSS, description="Blackjack split")
        view.game.split()
        await view.update_game(interaction)


class SurrenderButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="SURRENDER", style=discord.ButtonStyle.danger, emoji="🏳️", custom_id="bj:surrender")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        view.game.surrender()
        refund = view.bet / 2
        await db.update_user_balance(view.game.user_id, refund, TransactionType.GAME_WIN, description="Blackjack surrender refund")
        await view.update_game(interaction)


class InsuranceYesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="TAKE INSURANCE", style=discord.ButtonStyle.success, emoji="🛡️", custom_id="bj:ins_yes")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        user = await db.get_or_create_user(view.game.user_id)
        insurance_cost = view.bet / 2
        
        if user.balance < insurance_cost:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(insurance_cost)}** for insurance.",
                ephemeral=True
            )
            return
        
        await db.update_user_balance(view.game.user_id, -insurance_cost, TransactionType.GAME_LOSS, description="Blackjack insurance")
        view.game.take_insurance(True)
        await view.update_game(interaction)


class InsuranceNoButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="NO INSURANCE", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="bj:ins_no")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        view.game.take_insurance(False)
        await view.update_game(interaction)


class PlayAgainButton(discord.ui.Button):
    def __init__(self, last_bet: float):
        super().__init__(label=f"PLAY AGAIN (${last_bet:.0f})", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="bj:again", row=1)
        self.last_bet = last_bet
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        user = await db.get_or_create_user(view.game.user_id)
        if user.balance < self.last_bet:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(self.last_bet)}** to play.",
                ephemeral=True
            )
            return
        
        await db.update_user_balance(interaction.user.id, -self.last_bet, TransactionType.GAME_LOSS, description="Blackjack bet")
        
        config = load_config()
        game_config = config.get("games", {}).get("blackjack", {})
        game = create_blackjack_game(
            user_id=interaction.user.id,
            bet=self.last_bet,
            deck_count=game_config.get("deck_count", 6),
            penetration=game_config.get("penetration", 0.75),
            dealer_stands_soft_17=game_config.get("dealer_stands_soft_17", True),
            blackjack_payout=game_config.get("blackjack_payout", 1.5),
            insurance_payout=game_config.get("insurance_payout", 2.0),
            max_splits=game_config.get("max_splits", 3),
            allow_ace_resplit=game_config.get("allow_ace_resplit", False),
            allow_surrender=game_config.get("allow_surrender", True)
        )
        
        await cache.save_game_state(interaction.user.id, "blackjack", game.to_dict())
        
        new_view = EnhancedBlackjackView(game, view.cog, self.last_bet)
        
        if game.is_complete:
            await new_view.finish_game()
        
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)


class DoubleOrNothingButton(discord.ui.Button):
    def __init__(self, last_bet: float):
        super().__init__(label=f"DOUBLE OR NOTHING (${last_bet * 2:.0f})", style=discord.ButtonStyle.danger, emoji="🎲", custom_id="bj:double_nothing", row=1)
        self.double_bet = last_bet * 2
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        user = await db.get_or_create_user(view.game.user_id)
        if user.balance < self.double_bet:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(self.double_bet)}** to double or nothing.",
                ephemeral=True
            )
            return
        
        await db.update_user_balance(interaction.user.id, -self.double_bet, TransactionType.GAME_LOSS, description="Blackjack bet (double or nothing)")
        
        config = load_config()
        game_config = config.get("games", {}).get("blackjack", {})
        game = create_blackjack_game(user_id=interaction.user.id, bet=self.double_bet, deck_count=game_config.get("deck_count", 6))
        
        await cache.save_game_state(interaction.user.id, "blackjack", game.to_dict())
        
        new_view = EnhancedBlackjackView(game, view.cog, self.double_bet)
        
        if game.is_complete:
            await new_view.finish_game()
        
        await interaction.response.edit_message(embed=new_view.get_embed(), view=new_view)


class QuitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="QUIT", style=discord.ButtonStyle.secondary, emoji="🚪", custom_id="bj:quit", row=1)
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        embed = view.get_embed()
        embed.set_footer(text="Thanks for playing! • Developed by NaveL for JJI in 2025")
        await interaction.response.edit_message(embed=embed, view=None)


# ═══════════════════════════════════════════════════════════════════════════════
# PVP BLACKJACK VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class PvPBlackjackView(discord.ui.View):
    """PvP Blackjack game view"""
    
    def __init__(self, pvp_game: PvPBlackjackGame, player_id: int, cog: "GamesCog", timeout: float = 300):
        super().__init__(timeout=timeout)
        self.pvp_game = pvp_game
        self.player_id = player_id
        self.cog = cog
        self.message: discord.Message = None
        self.update_buttons()
    
    @property
    def hand(self) -> PvPPlayerHand:
        return self.pvp_game.get_player_hand(self.player_id)
    
    def update_buttons(self):
        self.clear_items()
        
        my_hand = self.hand
        if my_hand.is_done:
            if not self.pvp_game.is_complete:
                self.add_item(WaitingButton())
            return
        
        # Always can hit and stand
        self.add_item(PvPHitButton())
        self.add_item(PvPStandButton())
        
        # Can only double with 2 cards
        if len(my_hand.cards) == 2:
            self.add_item(PvPDoubleButton())
    
    def get_embed(self) -> discord.Embed:
        is_player1 = self.player_id == self.pvp_game.player1_id
        opponent_id = self.pvp_game.player2_id if is_player1 else self.pvp_game.player1_id
        
        if self.pvp_game.is_complete:
            if self.pvp_game.winner == self.player_id:
                color = 0x00FF00
                status = "🏆 YOU WIN THE DUEL!"
            elif self.pvp_game.winner is None:
                color = 0xFFD700
                status = "🤝 IT'S A TIE!"
            else:
                color = 0xFF0000
                status = "💀 YOU LOSE THE DUEL"
        else:
            color = 0x9B59B6
            status = "⚔️ PVP BLACKJACK"
        
        embed = discord.Embed(
            title="⚔️ PVP BLACKJACK DUEL",
            description=f"```ansi\n\u001b[1;35m{status}\u001b[0m\n```",
            color=color
        )
        
        embed.add_field(name="💰 POT", value=f"**{format_balance(self.pvp_game.pot)}**", inline=True)
        embed.add_field(name="🎯 OPPONENT", value=f"<@{opponent_id}>", inline=True)
        
        my_hand = self.hand
        player_value = my_hand.value
        value_display = f"**{player_value}**" if not my_hand.is_bust else f"~~{player_value}~~ BUST"
        
        embed.add_field(
            name=f"🃏 YOUR HAND — {value_display}",
            value=get_fancy_card_display(my_hand.cards),
            inline=False
        )
        
        opponent_hand = self.pvp_game.get_player_hand(opponent_id)
        if opponent_hand.is_done or self.pvp_game.is_complete:
            opp_value = opponent_hand.value
            opp_display = f"**{opp_value}**" if not opponent_hand.is_bust else f"~~{opp_value}~~ BUST"
            embed.add_field(
                name=f"👤 OPPONENT'S HAND — {opp_display}",
                value=get_fancy_card_display(opponent_hand.cards),
                inline=False
            )
        else:
            embed.add_field(name="👤 OPPONENT'S HAND", value="*Still playing...*", inline=False)
        
        if self.pvp_game.is_complete:
            if self.pvp_game.winner == self.player_id:
                embed.add_field(name="💎 YOUR WINNINGS", value=f"```diff\n+ {format_balance(self.pvp_game.pot)}\n```", inline=False)
            elif self.pvp_game.winner is None:
                embed.add_field(name="⚖️ TIE", value="Your bet has been refunded.", inline=False)
        
        embed.set_footer(text="PvP Blackjack • Developed by NaveL for JJI in 2025")
        return embed


class PvPHitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="HIT", style=discord.ButtonStyle.primary, emoji="🎴")
    
    async def callback(self, interaction: discord.Interaction):
        view: PvPBlackjackView = self.view
        if interaction.user.id != view.player_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        view.hand.hit()
        if view.hand.is_bust:
            view.pvp_game.mark_player_done(view.player_id)
        view.update_buttons()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class PvPStandButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="STAND", style=discord.ButtonStyle.secondary, emoji="🛑")
    
    async def callback(self, interaction: discord.Interaction):
        view: PvPBlackjackView = self.view
        if interaction.user.id != view.player_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        view.hand.stand()
        view.pvp_game.mark_player_done(view.player_id)
        view.update_buttons()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class PvPDoubleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="DOUBLE", style=discord.ButtonStyle.success, emoji="💰")
    
    async def callback(self, interaction: discord.Interaction):
        view: PvPBlackjackView = self.view
        if interaction.user.id != view.player_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        user = await db.get_or_create_user(view.player_id)
        double_cost = view.hand.bet
        
        if user.balance < double_cost:
            await interaction.response.send_message(f"❌ Insufficient balance! Need **{format_balance(double_cost)}**", ephemeral=True)
            return
        
        await db.update_user_balance(view.player_id, -double_cost, TransactionType.GAME_LOSS)
        view.pvp_game.pot += double_cost
        view.hand.double_down()
        view.pvp_game.mark_player_done(view.player_id)
        view.update_buttons()
        await interaction.response.edit_message(embed=view.get_embed(), view=view)


class WaitingButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Waiting for opponent...", style=discord.ButtonStyle.secondary, emoji="⏳", disabled=True)


class PvPQueueView(discord.ui.View):
    """View while waiting in PvP queue"""
    
    def __init__(self, user_id: int, bet: float, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.user_id = user_id
        self.bet = bet
    
    @discord.ui.button(label="CANCEL", style=discord.ButtonStyle.danger, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your queue!", ephemeral=True)
            return
        
        pvp_queue.remove_from_queue(self.user_id)
        await db.update_user_balance(self.user_id, self.bet, TransactionType.GAME_WIN, description="PvP queue cancelled - refund")
        
        embed = discord.Embed(title="⚔️ PVP BLACKJACK", description="Queue cancelled. Your bet has been refunded.", color=0xFF0000)
        await interaction.response.edit_message(embed=embed, view=None)
    
    async def on_timeout(self):
        pvp_queue.remove_from_queue(self.user_id)
        await db.update_user_balance(self.user_id, self.bet, TransactionType.GAME_WIN, description="PvP queue timeout - refund")


# ═══════════════════════════════════════════════════════════════════════════════
# GAMES COG
# ═══════════════════════════════════════════════════════════════════════════════

class GamesCog(commands.Cog):
    """Enhanced game commands with PvP"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    @app_commands.command(name="blackjack", description="🃏 Play Blackjack against the dealer! (Private game)")
    @app_commands.describe(bet="Amount to bet ($1 - $10,000)")
    async def blackjack(self, interaction: discord.Interaction, bet: float):
        """Start a solo blackjack game"""
        existing = await cache.get_game_state(interaction.user.id, "blackjack")
        if existing:
            await interaction.response.send_message("❌ You already have an active blackjack game! Finish it first.", ephemeral=True)
            return
        
        user = await db.get_or_create_user(interaction.user.id)
        
        config = self.config.get("economy", {})
        min_bet = config.get("min_bet", 1)
        max_bet = config.get("max_bet", 10000)
        max_pct = config.get("max_bet_percentage", 100)
        
        is_valid, error = validate_bet(bet, user.balance, min_bet, max_bet, max_pct)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        success, _, _ = await db.update_user_balance(interaction.user.id, -bet, TransactionType.GAME_LOSS, description="Blackjack bet")
        
        if not success:
            await interaction.response.send_message("❌ Failed to place bet. Please try again.", ephemeral=True)
            return
        
        # Bet goes to server budget (closed-loop economy)
        await db.update_server_budget(bet)
        
        game_config = self.config.get("games", {}).get("blackjack", {})
        game = create_blackjack_game(
            user_id=interaction.user.id,
            bet=bet,
            deck_count=game_config.get("deck_count", 6),
            penetration=game_config.get("penetration", 0.75),
            dealer_stands_soft_17=game_config.get("dealer_stands_soft_17", True),
            blackjack_payout=game_config.get("blackjack_payout", 1.5),
            insurance_payout=game_config.get("insurance_payout", 2.0),
            max_splits=game_config.get("max_splits", 3),
            allow_ace_resplit=game_config.get("allow_ace_resplit", False),
            allow_surrender=game_config.get("allow_surrender", True)
        )
        
        await cache.save_game_state(interaction.user.id, "blackjack", game.to_dict())
        
        view = EnhancedBlackjackView(game, self, bet)
        
        if game.is_complete:
            await view.finish_game()
        
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()
        
        metrics.set_active_games("blackjack", 1)
    
    @app_commands.command(name="blackjack_pvp", description="⚔️ Challenge another player to Blackjack PvP!")
    @app_commands.describe(bet="Amount to bet - will be matched by opponent")
    async def blackjack_pvp(self, interaction: discord.Interaction, bet: float):
        """Join PvP blackjack queue"""
        user = await db.get_or_create_user(interaction.user.id)
        
        config = self.config.get("economy", {})
        min_bet = config.get("min_bet", 1)
        max_bet = config.get("max_bet", 10000)
        
        is_valid, error = validate_bet(bet, user.balance, min_bet, max_bet, 100)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        await db.update_user_balance(interaction.user.id, -bet, TransactionType.GAME_LOSS, description="PvP Blackjack bet")
        
        match = pvp_queue.add_to_queue(interaction.user.id, bet, interaction)
        
        if match:
            opponent_id, opponent_data = match
            
            pvp_game = PvPBlackjackGame(player1_id=opponent_id, player2_id=interaction.user.id, bet=min(bet, opponent_data["bet"]))
            
            game_id = f"{opponent_id}_{interaction.user.id}"
            pvp_queue.active_games[game_id] = pvp_game
            
            view1 = PvPBlackjackView(pvp_game, opponent_id, self)
            view2 = PvPBlackjackView(pvp_game, interaction.user.id, self)
            
            try:
                opp_interaction = opponent_data["interaction"]
                await opp_interaction.edit_original_response(embed=view1.get_embed(), view=view1)
            except:
                pass
            
            await interaction.response.send_message(embed=view2.get_embed(), view=view2)
        else:
            embed = discord.Embed(
                title="⚔️ PVP BLACKJACK QUEUE",
                description="```ansi\n\u001b[1;33mSearching for opponent...\u001b[0m\n```",
                color=0x9B59B6
            )
            embed.add_field(name="💰 Your Bet", value=format_balance(bet), inline=True)
            embed.add_field(name="👥 In Queue", value=str(pvp_queue.get_queue_size()), inline=True)
            embed.set_footer(text="You'll be matched with a player betting a similar amount...")
            
            view = PvPQueueView(interaction.user.id, bet)
            await interaction.response.send_message(embed=embed, view=view)
    
    @app_commands.command(name="coinflip", description="🪙 Flip a coin - heads or tails! (Private game)")
    @app_commands.describe(bet="Amount to bet ($1 - $10,000)", side="Choose your side")
    async def coinflip(self, interaction: discord.Interaction, bet: float, side: Literal["heads", "tails"]):
        """Play coinflip"""
        user = await db.get_or_create_user(interaction.user.id)
        
        config = self.config.get("economy", {})
        min_bet = config.get("min_bet", 1)
        max_bet = config.get("max_bet", 10000)
        max_pct = config.get("max_bet_percentage", 100)
        
        is_valid, error = validate_bet(bet, user.balance, min_bet, max_bet, max_pct)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        success, _, _ = await db.update_user_balance(interaction.user.id, -bet, TransactionType.GAME_LOSS, description="Coinflip bet")
        
        if not success:
            await interaction.response.send_message("❌ Failed to place bet. Please try again.", ephemeral=True)
            return
        
        # Bet goes to server budget (closed-loop economy)
        await db.update_server_budget(bet)
        
        game, error = create_coinflip_game(interaction.user.id, bet, side)
        if error:
            await db.update_user_balance(interaction.user.id, bet, TransactionType.GAME_WIN, description="Coinflip bet refund")
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        frames = ["🪙", "⚪", "🪙", "⚪", "🪙", "⚪"]
        
        embed = discord.Embed(title="🪙 COINFLIP", description=f"```\n{frames[0]}\n\nFlipping...\n```", color=0xFFD700)
        embed.add_field(name="Your Choice", value=side.upper(), inline=True)
        embed.add_field(name="Bet", value=format_balance(bet), inline=True)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        message = await interaction.original_response()
        
        for i in range(1, len(frames)):
            await asyncio.sleep(0.4)
            embed.description = f"```\n{frames[i]}\n\nFlipping...\n```"
            try:
                await message.edit(embed=embed)
            except:
                pass
        
        await asyncio.sleep(0.5)
        
        game_config = self.config.get("games", {}).get("coinflip", {})
        edge_chance = game_config.get("edge_chance", 0.005)
        result = game.flip(edge_chance)
        
        if result == CoinflipResult.WIN:
            # Player wins - calculate tax only on PROFIT, not on bet return
            profit_amount = game.winnings  # This is just the profit (equal to bet for 1:1)
            
            economy = await db.get_server_economy()
            net_profit, tax = calculate_tax(profit_amount, economy.tax_rate)
            
            # Total payout = bet back + net profit after tax
            total_payout = bet + net_profit
            
            # Deduct total payout from server budget
            await db.update_server_budget(-total_payout)
            
            # Give player their winnings (no additional tax deduction - already calculated)
            await db.update_user_balance(interaction.user.id, total_payout, TransactionType.GAME_WIN, description="Coinflip win")
            
            if tax > 0:
                await db.add_taxes_collected(tax)
            
            color = 0x00FF00
            result_text = f"🎉 **{game.result_side.upper()}** - YOU WIN!"
            profit = f"+{format_balance(net_profit)}"  # Show actual profit after tax
        elif result == CoinflipResult.EDGE:
            # Edge - money stays in server budget (already there)
            color = 0x9B59B6
            result_text = "😱 **EDGE** - The coin landed on its edge!"
            profit = f"-{format_balance(bet)}"
        else:
            # Player loses - money stays in server budget (already there)
            color = 0xFF0000
            result_text = f"💔 **{game.result_side.upper()}** - YOU LOSE"
            profit = f"-{format_balance(bet)}"
        
        embed = discord.Embed(title="🪙 COINFLIP - RESULT", description=f"```ansi\n\u001b[1;33m{result_text}\u001b[0m\n```", color=color)
        embed.add_field(name="Your Choice", value=side.upper(), inline=True)
        embed.add_field(name="Result", value=game.result_side.upper() if game.result_side else "EDGE", inline=True)
        embed.add_field(name="Bet", value=format_balance(bet), inline=True)
        embed.add_field(name="Profit/Loss", value=profit, inline=True)
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        await message.edit(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesCog(bot))
