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
import json
import os

from src.services.database import db
from src.services.cache import cache
from src.services.economy_logger import economy_logger, EconomyAction
from src.models.database import TransactionType, GameType
from src.games.blackjack import create_blackjack_game, BlackjackGame, GameState, PvPBlackjackGame, Shoe, Hand
from src.games.coinflip import create_coinflip_game, CoinflipResult, CoinSide
from src.utils.helpers import format_balance, validate_bet, calculate_tax, load_config, get_standard_footer
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
            continue

        # Parse card string - last character is suit
        suit = card[-1]
        rank = card[:-1]

        # Use simple emoji/symbols without markdown for clarity
        if suit == "♥":
            display = f"{rank}♥"
        elif suit == "♦":
            display = f"{rank}♦"
        elif suit == "♠":
            display = f"{rank}♠"
        elif suit == "♣":
            display = f"{rank}♣"
        else:
            display = f"{rank}{suit}"

        result.append(display)

    return " ".join(result)


class PvPInviteView(discord.ui.View):
    """View for accepting a PvP challenge"""
    def __init__(self, challenger_id: int, bet: float, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.challenger_id = challenger_id
        self.bet = bet
        self.accepted = False
        self.message: discord.Message = None

    @discord.ui.button(label="ACCEPT CHALLENGE", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Prevent challenger from accepting their own invite (though they shouldn't see it if logic is right)
        if interaction.user.id == self.challenger_id:
            await interaction.response.send_message("❌ You can't accept your own challenge!", ephemeral=True)
            return

        self.accepted = True
        self.stop()
        
        # Start game logic handled in command
        # Here we just validate balance and signal acceptance
        
        user = await db.get_or_create_user(interaction.user.id)
        if user.balance < self.bet:
            await interaction.response.send_message(f"❌ You don't have enough funds! Need **{format_balance(self.bet)}**.", ephemeral=True)
            self.accepted = False
            return

        # Disable buttons
        for item in self.children:
            item.disabled = True
        
        # Edit the message first to show it's being processed and prevent double clicks
        await interaction.response.edit_message(view=self)
        
        # Proceed to start game
        await self.cog.start_pvp_game(interaction, self.challenger_id, interaction.user.id, self.bet)

    @discord.ui.button(label="DECLINE", style=discord.ButtonStyle.danger, emoji="✖️")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.challenger_id:
             # Challenger cancelling
             await interaction.response.send_message("Challenge cancelled.", ephemeral=True)
             self.stop()
             await self.message.delete()
             # Refund challenger handled by timeout/cancellation logic in command?
             # If command waits, it will see self.accepted is False.
             return

        await interaction.response.send_message("Challenge declined.", ephemeral=True)
        self.stop()
        await self.message.delete()


# ═══════════════════════════════════════════════════════════════════════════════
# ENHANCED BLACKJACK VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class EnhancedBlackjackView(discord.ui.View):
    """Beautiful interactive blackjack game view with Play Again"""
    
    def __init__(self, game: BlackjackGame, cog: "GamesCog", bet: float, timeout: float = None):
        super().__init__(timeout=timeout)  # None = no timeout
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
            # Show BUST clearly instead of number > 21
            if dealer_value == "BUST" or (isinstance(dealer_value, int) and dealer_value > 21):
                dealer_header = "🎩 DEALER — **BUST** 💥"
            else:
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
            is_bust = hand.get("is_bust", False) or numeric_value > 21  # Extra safety check
            is_blackjack = hand.get("is_blackjack", False)
            is_current = hand.get("is_current", False)
            hand_bet = hand.get("bet_amount", self.bet)  # Numeric bet amount
            
            if is_bust:
                status_icon = "💥 BUST"
                value_display = "**BUST**"  # Show BUST instead of the number
            elif is_blackjack:
                status_icon = "🎰 BLACKJACK!"
                value_display = "**21**"
            elif numeric_value == 21:
                status_icon = "✨ 21!"
                value_display = "**21**"
            else:
                status_icon = ""
                value_display = f"**{numeric_value}**"
            
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
            embed.set_footer(text=f"{random.choice(tips)} • {get_standard_footer()}")
        else:
            embed.set_footer(text=f"🎰 Press 'Play Again' for another round! • {get_standard_footer()}")
        
        return embed
    
    async def on_timeout(self):
        if not self.game.is_complete:
            while not self.game.is_complete:
                self.game.stand()
            await self.finish_game()
    
    async def finish_game(self):
        net_result = self.game.get_net_result()
        total_bet = self.game.total_bet  # Use total_bet for split/double calculations
        
        # Get state before any changes
        user = await db.get_or_create_user(self.game.user_id)
        economy = await db.get_server_economy()
        user_before = user.balance
        budget_before = economy.total_budget
        
        if net_result != 0:
            if net_result > 0:
                # Player wins - resolve atomically (budget + balance + tax in one transaction)
                profit_amount = net_result  # This is just the profit (already accounts for split/double)
                
                result = await db.resolve_game_win_atomic(
                    self.game.user_id,
                    total_bet,
                    profit_amount,
                    economy.tax_rate,
                    description="Blackjack win"
                )
                
                if not result["success"]:
                    return
                
                net_profit = result["net_profit"]
                tax = result["tax"]
                total_payout = result["total_payout"]
                
                if tax > 0:
                    metrics.track_tax(tax)
                
                metrics.track_game("blackjack", "win", total_bet)
                
                # Log game result
                await economy_logger.log_game(
                    game_name="Blackjack",
                    user_id=self.game.user_id,
                    user_name=str(self.game.user_id),
                    bet=total_bet,
                    result="WIN",
                    winnings=total_payout,
                    profit=net_profit,
                    user_before=result["before_balance"],
                    user_after=result["after_balance"],
                    budget_before=result["before_budget"],
                    budget_after=result["after_budget"],
                    details={
                        "Initial Bet": f"${self.bet:,.2f}",
                        "Total Bet": f"${total_bet:,.2f}",
                        "Gross Profit": f"${profit_amount:,.2f}",
                        "Tax": f"${tax:,.2f}",
                        "Net Profit": f"${net_profit:,.2f}",
                        "Total Payout": f"${total_payout:,.2f}"
                    }
                )
            else:
                # Player loses - money stays in server budget (already added when bet placed)
                loss_amount = abs(net_result)  # Actual loss (accounts for split/double)
                metrics.track_game("blackjack", "lose", total_bet)
                
                # Calculate balance BEFORE bet was placed for accurate logging
                balance_before_bet = user_before + total_bet  # Restore what balance was before bet
                
                # Log game result
                economy_after = await db.get_server_economy()
                await economy_logger.log_game(
                    game_name="Blackjack",
                    user_id=self.game.user_id,
                    user_name=str(self.game.user_id),
                    bet=total_bet,
                    result="LOSS",
                    winnings=0,
                    profit=-loss_amount,
                    user_before=balance_before_bet,  # Balance BEFORE bet was placed
                    user_after=user_before,  # Current balance (after bet was taken at start)
                    budget_before=budget_before - total_bet,  # Budget BEFORE bet was added
                    budget_after=economy_after.total_budget,
                    details={
                        "Initial Bet": f"${self.bet:,.2f}",
                        "Total Bet": f"${total_bet:,.2f}",
                        "Total Lost": f"${loss_amount:,.2f}"
                    }
                )
        else:
            # Push - refund atomically (no profit, no tax)
            result = await db.resolve_game_win_atomic(
                self.game.user_id,
                total_bet,
                0,  # No profit on push
                0,  # No tax on refund
                description="Blackjack push - refund"
            )
            
            if not result["success"]:
                return
            
            metrics.track_game("blackjack", "push", total_bet)
            
            # Log game result
            await economy_logger.log_game(
                game_name="Blackjack",
                user_id=self.game.user_id,
                user_name=str(self.game.user_id),
                bet=total_bet,
                result="PUSH",
                winnings=total_bet,
                profit=0,
                user_before=result["before_balance"],
                user_after=result["after_balance"],
                budget_before=result["before_budget"],
                budget_after=result["after_budget"],
                details={
                    "Initial Bet": f"${self.bet:,.2f}",
                    "Total Bet": f"${total_bet:,.2f}",
                    "Refunded": f"${total_bet:,.2f}"
                }
            )
        
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
        
        double_cost = view.game.current_hand.bet
        
        result = await db.place_bet_atomic(view.game.user_id, double_cost, description="Blackjack double down")
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(double_cost)}** to double.",
                ephemeral=True
            )
            return
        
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
        
        split_cost = view.game.current_hand.bet
        
        result = await db.place_bet_atomic(view.game.user_id, split_cost, description="Blackjack split")
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(split_cost)}** to split.",
                ephemeral=True
            )
            return
        
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
        # Refund half the bet atomically
        await db.resolve_game_win_atomic(
            view.game.user_id,
            refund,  # Return half the bet
            0,  # No profit
            0,  # No tax on refund
            description="Blackjack surrender refund"
        )
        await view.update_game(interaction)


class InsuranceYesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="TAKE INSURANCE", style=discord.ButtonStyle.success, emoji="🛡️", custom_id="bj:ins_yes")
    
    async def callback(self, interaction: discord.Interaction):
        view: EnhancedBlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("❌ This isn't your game!", ephemeral=True)
            return
        
        insurance_cost = view.bet / 2
        
        result = await db.place_bet_atomic(view.game.user_id, insurance_cost, description="Blackjack insurance")
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(insurance_cost)}** for insurance.",
                ephemeral=True
            )
            return
        
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
        
        result = await db.place_bet_atomic(interaction.user.id, self.last_bet, description="Blackjack bet")
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(self.last_bet)}** to play.",
                ephemeral=True
            )
            return
        
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
        
        result = await db.place_bet_atomic(interaction.user.id, self.double_bet, description="Blackjack bet (double or nothing)")
        if not result["success"]:
            await interaction.response.send_message(
                f"❌ Insufficient balance! Need **{format_balance(self.double_bet)}** to double or nothing.",
                ephemeral=True
            )
            return
        
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
        embed.set_footer(text=f"Thanks for playing! • {get_standard_footer()}")
        await interaction.response.edit_message(embed=embed, view=None)


# ═══════════════════════════════════════════════════════════════════════════════
# PVP BLACKJACK VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class PvPBlackjackView(discord.ui.View):
    """PvP Blackjack game view"""
    
    def __init__(self, game_id: str, pvp_game: PvPBlackjackGame, cog: "GamesCog", timeout: float = 300):
        super().__init__(timeout=timeout)
        self.game_id = game_id
        self.pvp_game = pvp_game
        self.cog = cog
        self.message: discord.Message = None
        self.update_buttons()
    
    def update_buttons(self):
        self.clear_items()
        
        if self.pvp_game.state == GameState.COMPLETE:
            # Game finished — offer rematch and close controls
            self.add_item(PvPPlayAgainButton())
            self.add_item(ClosePVPButton())
            return
        
        # Buttons for current turn player
        current_turn = self.pvp_game.current_turn_player_id
        
        if current_turn:
            self.add_item(PvPHitButton(current_turn))
            self.add_item(PvPStandButton(current_turn))

            # Double check
            hand = self.pvp_game.current_active_hand
            if hand and hand.can_double:
                self.add_item(PvPDoubleButton(current_turn))

            if hand and hand.can_split:
                self.add_item(PvPSplitButton(current_turn))

    def get_embed(self) -> discord.Embed:
        # Determine status color/text
        if self.pvp_game.state == GameState.PLAYER_A_TURN:
            status = f"🎲 <@{self.pvp_game.player_a_id}>'s TURN"
            color = 0x3498DB
        elif self.pvp_game.state == GameState.PLAYER_B_TURN:
            status = f"🎲 <@{self.pvp_game.player_b_id}>'s TURN"
            color = 0xE67E22
        elif self.pvp_game.state == GameState.COMPLETE:
            status = "🏁 GAME OVER"
            color = 0x2ECC71
        else:
            status = "⏳ WAITING"
            color = 0x95A5A6

        embed = discord.Embed(
            title="⚔️ PVP BLACKJACK DUEL",
            description=status,
            color=color
        )
        
        # Players: render hands in clear code blocks (dealer removed for PvP)
        def render_player_block(hands, current_turn_state, current_index, results_list=None):
            lines = []
            for i, hand in enumerate(hands):
                cards = [c.to_dict()["rank"]+c.to_dict()["suit"] for c in hand.cards]
                
                # Clear value display - BUST shows as BUST, not the number
                if hand.is_bust:
                    val_display = "BUST"
                elif hand.is_blackjack:
                    val_display = "21 BJ!"
                else:
                    val_display = str(hand.value)
                
                pointer = " ◄" if (current_turn_state and i == current_index) else ""
                
                # Show result if game complete
                result_str = ""
                if results_list and i < len(results_list):
                    res_type, amt = results_list[i]
                    if res_type.value in ("win", "blackjack"):
                        result_str = f" ✓ +${amt:.0f}"
                    elif res_type.value in ("lose", "bust"):
                        result_str = f" ✗ -${abs(amt):.0f}"
                    elif res_type.value == "push":
                        result_str = " = PUSH"
                
                lines.append(f"Hand {i+1}: {get_fancy_card_display(cards)} [{val_display}]{pointer}{result_str}")
            return "```text\n" + "\n".join(lines) + "\n```"

        # Get results for display
        a_results = self.pvp_game.results.get(self.pvp_game.player_a_id) if self.pvp_game.state == GameState.COMPLETE else None
        b_results = self.pvp_game.results.get(self.pvp_game.player_b_id) if self.pvp_game.state == GameState.COMPLETE else None
        
        pa_label = f"<@{self.pvp_game.player_a_id}>"
        a_block = render_player_block(self.pvp_game.player_a_hands, self.pvp_game.state == GameState.PLAYER_A_TURN, self.pvp_game.current_hand_index_a, a_results)
        embed.add_field(name=f"🔵 Player A ({pa_label}) — ${self.pvp_game.player_a_bet:.0f}", value=a_block, inline=False)

        pb_label = f"<@{self.pvp_game.player_b_id}>"
        b_block = render_player_block(self.pvp_game.player_b_hands, self.pvp_game.state == GameState.PLAYER_B_TURN, self.pvp_game.current_hand_index_b, b_results)
        embed.add_field(name=f"🟠 Player B ({pb_label}) — ${self.pvp_game.player_b_bet:.0f}", value=b_block, inline=False)
        
        # Final summary
        if self.pvp_game.state == GameState.COMPLETE:
            a_total = sum(r[1] for r in self.pvp_game.results.get(self.pvp_game.player_a_id, []))
            b_total = sum(r[1] for r in self.pvp_game.results.get(self.pvp_game.player_b_id, []))
            
            # Determine winner
            if a_total > b_total:
                winner = f"🏆 <@{self.pvp_game.player_a_id}> WINS!"
            elif b_total > a_total:
                winner = f"🏆 <@{self.pvp_game.player_b_id}> WINS!"
            else:
                winner = "🤝 TIE GAME"
            
            summary = f"{winner}\n\n"
            summary += f"<@{self.pvp_game.player_a_id}>: **{'+' if a_total >= 0 else ''}{a_total:.0f}**\n"
            summary += f"<@{self.pvp_game.player_b_id}>: **{'+' if b_total >= 0 else ''}{b_total:.0f}**"
            
            embed.add_field(name="📊 FINAL RESULT", value=summary, inline=False)

        embed.set_footer(text="PvP Blackjack • Winner takes opponent's bet")

        return embed

    async def on_timeout(self):
        if self.pvp_game.state != GameState.COMPLETE:
            # Auto-stand current player
            current_id = self.pvp_game.current_turn_player_id
            if current_id:
                await self.cog.process_pvp_action(self.game_id, "stand", current_id, None)

class PvPHitButton(discord.ui.Button):
    def __init__(self, player_id: int):
        super().__init__(label="HIT", style=discord.ButtonStyle.primary, emoji="🎴")
        self.player_id = player_id
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Not your turn!", ephemeral=True)
            return
        await self.view.cog.process_pvp_action(self.view.game_id, "hit", self.player_id, interaction)

class PvPStandButton(discord.ui.Button):
    def __init__(self, player_id: int):
        super().__init__(label="STAND", style=discord.ButtonStyle.secondary, emoji="🛑")
        self.player_id = player_id
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Not your turn!", ephemeral=True)
            return
        await self.view.cog.process_pvp_action(self.view.game_id, "stand", self.player_id, interaction)

class PvPDoubleButton(discord.ui.Button):
    def __init__(self, player_id: int):
        super().__init__(label="DOUBLE", style=discord.ButtonStyle.success, emoji="💰")
        self.player_id = player_id
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Not your turn!", ephemeral=True)
            return
        await self.view.cog.process_pvp_action(self.view.game_id, "double", self.player_id, interaction)

class PvPSplitButton(discord.ui.Button):
    def __init__(self, player_id: int):
        super().__init__(label="SPLIT", style=discord.ButtonStyle.success, emoji="✂️")
        self.player_id = player_id
    
    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Not your turn!", ephemeral=True)
            return
        await self.view.cog.process_pvp_action(self.view.game_id, "split", self.player_id, interaction)


class PvPPlayAgainButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Play Again", style=discord.ButtonStyle.primary, emoji="🔁")

    async def callback(self, interaction: discord.Interaction):
        # Allow either participant to request a rematch; start a fresh PvP game with same bet
        view: PvPBlackjackView = self.view
        if not view or not view.pvp_game:
            await interaction.response.send_message("❌ Can't start rematch right now.", ephemeral=True)
            return

        p1 = view.pvp_game.player_a_id
        p2 = view.pvp_game.player_b_id
        bet = view.pvp_game.player_a_bet

        # Only participants can start a rematch
        if interaction.user.id not in (p1, p2):
            await interaction.response.send_message("❌ Only participants can start a rematch.", ephemeral=True)
            return

        # Defer response so start_pvp_game can use followup sends
        try:
            await interaction.response.defer()
        except Exception:
            # If defer fails, try a simple acknowledgement
            try:
                await interaction.response.send_message("⏳ Starting rematch...", ephemeral=True)
            except Exception:
                pass

        # Use cog helper to start a new PvP game; this will perform balance checks
        await view.cog.start_pvp_game(interaction, p1, p2, bet)


class ClosePVPButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="CLOSE", style=discord.ButtonStyle.secondary, emoji="❌")

    async def callback(self, interaction: discord.Interaction):
        view: PvPBlackjackView = self.view
        if not view or not view.pvp_game:
            await interaction.response.send_message("❌ Nothing to close.", ephemeral=True)
            return

        # Only participants can close the board
        uid = interaction.user.id
        if uid not in (view.pvp_game.player_a_id, view.pvp_game.player_b_id):
            await interaction.response.send_message("❌ Only participants can close this game.", ephemeral=True)
            return

        embed = view.get_embed()
        embed.set_footer(text="Game closed by player.")
        await interaction.response.edit_message(embed=embed, view=None)


# ═══════════════════════════════════════════════════════════════════════════════
# GAMES COG
# ═══════════════════════════════════════════════════════════════════════════════

class GamesCog(commands.Cog):
    """Enhanced game commands with PvP"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    @app_commands.command(name="blackjack", description="Play Blackjack against the dealer")
    @app_commands.describe(bet="Amount to bet ($1 - $10,000)")
    @game_rate_limited(cooldown_seconds=10)
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
        
        result = await db.place_bet_atomic(interaction.user.id, bet, description="Blackjack bet")
        if not result["success"]:
            await interaction.response.send_message("❌ Failed to place bet. Please try again.", ephemeral=True)
            return
        
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
    
    @app_commands.command(name="blackjack_pvp", description="Challenge another player to Blackjack PvP")
    @app_commands.describe(opponent="The player you want to challenge", bet="Amount to bet")
    @game_rate_limited(cooldown_seconds=30)
    async def blackjack_pvp(self, interaction: discord.Interaction, opponent: discord.User, bet: float):
        """Start a PvP blackjack game"""
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("❌ You can't challenge yourself!", ephemeral=True)
            return

        if opponent.bot:
            await interaction.response.send_message("❌ You can't challenge a bot!", ephemeral=True)
            return

        user = await db.get_or_create_user(interaction.user.id)
        
        config = self.config.get("economy", {})
        min_bet = config.get("min_bet", 1)
        max_bet = config.get("max_bet", 10000)
        
        is_valid, error = validate_bet(bet, user.balance, min_bet, max_bet, 100)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return

        # Create invite view
        view = PvPInviteView(challenger_id=interaction.user.id, bet=bet)
        view.cog = self

        embed = discord.Embed(
            title="⚔️ PVP BLACKJACK CHALLENGE",
            description=f"<@{interaction.user.id}> challenges <@{opponent.id}> to a duel!",
            color=0x9B59B6
        )
        embed.add_field(name="💰 Bet", value=format_balance(bet))
        embed.set_footer(text=f"Waiting for {opponent.display_name} to accept...")

        await interaction.response.send_message(content=f"<@{opponent.id}>", embed=embed, view=view)
        view.message = await interaction.original_response()

    async def start_pvp_game(self, interaction: discord.Interaction, p1_id: int, p2_id: int, bet: float):
        # 1. Lock funds and Create Session Atomically
        # Re-check balances (Double check before DB op, though DB op handles locking)
        u1 = await db.get_user(p1_id)
        u2 = await db.get_user(p2_id)

        if u1.balance < bet or u2.balance < bet:
            await interaction.followup.send("❌ One of the players has insufficient funds now!", ephemeral=True)
            return

        # 2. Init Game
        import uuid
        game_id = str(uuid.uuid4())

        shoe = Shoe(deck_count=6)
        game = PvPBlackjackGame(
            player_a_id=p1_id,
            player_b_id=p2_id,
            player_a_bet=bet,
            player_b_bet=bet,
            shoe=shoe
        )
        game.deal_initial()

        # 3. Create Session in DB Atomically with Bet Deduction
        success, msg, session = await db.start_pvp_game_atomic(
            game_id=game_id,
            player_a_id=p1_id,
            player_b_id=p2_id,
            bet_amount=bet,
            state=game.state.value,
            shoe_state=json.dumps(game.shoe.to_dict()),
            player_a_hand=json.dumps([h.to_dict() for h in game.player_a_hands]),
            player_b_hand=json.dumps([h.to_dict() for h in game.player_b_hands]),
            dealer_hand=json.dumps(game.dealer_hand.to_dict())
        )

        if not success:
            await interaction.followup.send(f"❌ Failed to start game: {msg}", ephemeral=True)
            return
        
        # 4. Show Board
        # Use short timeout for turn actions
        view = PvPBlackjackView(game_id, game, self, timeout=30)

        # Try to cache readable display names on the view so embeds show friendly names
        try:
            guild = interaction.guild
            if guild:
                try:
                    member_a = guild.get_member(p1_id) or await guild.fetch_member(p1_id)
                except Exception:
                    member_a = None
                try:
                    member_b = guild.get_member(p2_id) or await guild.fetch_member(p2_id)
                except Exception:
                    member_b = None

                if member_a:
                    view.player_a_name = member_a.display_name
                if member_b:
                    view.player_b_name = member_b.display_name
        except Exception:
            # Best-effort only; fall back to mentions in embed
            pass

        embed = view.get_embed()

        # Use followup since the interaction was already responded to in the View
        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message
        
        # Update session with message ID
        await db.update_pvp_game_session(game_id=game_id, state=game.state.value, shoe_state=json.dumps(game.shoe.to_dict()), player_a_hand=json.dumps([h.to_dict() for h in game.player_a_hands]), player_b_hand=json.dumps([h.to_dict() for h in game.player_b_hands]), dealer_hand=json.dumps(game.dealer_hand.to_dict()), message_id=view.message.id, channel_id=view.message.channel.id)

    async def process_pvp_action(self, game_id: str, action: str, user_id: int, interaction: Optional[discord.Interaction]):
        # Load game with locking for update if needed
        # But we need to know what action it is first?
        # Actually, get_pvp_game_session logic handles 'for_update' flag.
        # But we don't know if we need update yet?
        # We can just always lock for consistency in actions to prevent race conditions.

        session = await db.get_pvp_game_session(game_id, for_update=True)
        if not session:
            if interaction: await interaction.response.send_message("❌ Game not found!", ephemeral=True)
            return
            
        # Reconstruct Game Object
        # Resolve Discord IDs from internal user IDs WITHOUT accessing lazy relationships
        player_a_user = await db.get_user_by_id(session.player_a_id)
        player_b_user = await db.get_user_by_id(session.player_b_id)
        player_a_discord = player_a_user.discord_id if player_a_user else session.player_a_id
        player_b_discord = player_b_user.discord_id if player_b_user else session.player_b_id

        game = PvPBlackjackGame(
            player_a_id=player_a_discord,
            player_b_id=player_b_discord,
            player_a_bet=session.player_a_bet,
            player_b_bet=session.player_b_bet,
            shoe=Shoe.from_dict(json.loads(session.shoe_state))
        )
        game.state = GameState(session.state)
        game.player_a_hands = [Hand.from_dict(h) for h in json.loads(session.player_a_hand)]
        game.player_b_hands = [Hand.from_dict(h) for h in json.loads(session.player_b_hand)]
        game.dealer_hand = Hand.from_dict(json.loads(session.dealer_hand))
        if session.current_turn: # Logic uses internal state for turn, but we verify
             pass

        # Apply Action
        updated = False
        check_funds_amount = 0.0

        # Calculate cost for Double/Split
        if action in ["double", "split"]:
            hand = game.current_active_hand
            if hand:
                check_funds_amount = hand.bet

        if action == "hit":
            bust, _ = game.hit(user_id)
            updated = True
        elif action == "stand":
            game.stand(user_id)
            updated = True
        elif action == "double":
            game.double(user_id)
            updated = True
        elif action == "split":
            game.split(user_id)
            updated = True
            
        if updated:
            # Save State with Fund Check if needed
            success, msg = await db.update_pvp_game_session(
                game_id=game_id,
                state=game.state.value,
                shoe_state=json.dumps(game.shoe.to_dict()),
                player_a_hand=json.dumps([h.to_dict() for h in game.player_a_hands]),
                player_b_hand=json.dumps([h.to_dict() for h in game.player_b_hands]),
                dealer_hand=json.dumps(game.dealer_hand.to_dict()),
                current_turn=game.current_turn_player_id,
                check_funds_for_player=user_id if check_funds_amount > 0 else None,
                deduct_amount=check_funds_amount
            )
            
            if not success:
                if interaction:
                    await interaction.response.send_message(f"❌ Action failed: {msg}", ephemeral=True)
                return
            
            # Update UI
            # If interaction exists, edit message.
            # If auto-stand (timeout), use stored message_id.
            
            view = PvPBlackjackView(game_id, game, self)
            embed = view.get_embed()

            if interaction:
                await interaction.response.edit_message(embed=embed, view=view)
            else:
                # Fetch message
                try:
                    channel = self.bot.get_channel(session.channel_id)
                    message = await channel.fetch_message(session.message_id)
                    await message.edit(embed=embed, view=view)
                except:
                    pass
            
            # If Complete, Payout
            if game.state == GameState.COMPLETE:
                # Fetch updated session to get correct bet amounts (after doubles/splits)
                updated_session = await db.get_pvp_game_session(game_id)
                if updated_session:
                    # Use bet amounts from DB which include doubles/splits
                    actual_bet_a = updated_session.player_a_bet
                    actual_bet_b = updated_session.player_b_bet
                else:
                    # Fallback to game values
                    actual_bet_a = game.player_a_bet
                    actual_bet_b = game.player_b_bet
                
                # Construct results dict {uid: profit}
                # game.results contains net profit/loss amounts:
                # Win: +amount (profit), Lose: -amount (loss), Push: 0
                payout_map = {}

                # Player A
                if game.player_a_id in game.results:
                    total_payout_a = sum(amount for _, amount in game.results[game.player_a_id])
                    payout_map[game.player_a_id] = total_payout_a

                # Player B
                if game.player_b_id in game.results:
                    total_payout_b = sum(amount for _, amount in game.results[game.player_b_id])
                    payout_map[game.player_b_id] = total_payout_b

                await db.resolve_pvp_payout(
                    player_a_id=game.player_a_id,
                    player_b_id=game.player_b_id,
                    player_a_bet=actual_bet_a,
                    player_b_bet=actual_bet_b,
                    results=payout_map
                )

                # Delete session
                await db.delete_pvp_game_session(game_id)
    
    @app_commands.command(name="coinflip", description="Flip a coin - heads or tails")
    @app_commands.describe(bet="Amount to bet ($1 - $10,000)", side="Choose your side")
    @game_rate_limited(cooldown_seconds=5)
    async def coinflip(self, interaction: discord.Interaction, bet: float, side: Literal["heads", "tails"]):
        """Play coinflip"""
        user = await db.get_or_create_user(interaction.user.id)
        user_before = user.balance
        economy = await db.get_server_economy()
        budget_before = economy.total_budget
        
        config = self.config.get("economy", {})
        min_bet = config.get("min_bet", 1)
        max_bet = config.get("max_bet", 10000)
        max_pct = config.get("max_bet_percentage", 100)
        
        is_valid, error = validate_bet(bet, user.balance, min_bet, max_bet, max_pct)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        # Place bet ATOMICALLY - deduct from user and add to budget in one transaction
        bet_result = await db.place_bet_atomic(interaction.user.id, bet, description="Coinflip bet")
        
        if not bet_result["success"]:
            await interaction.response.send_message(f"❌ {bet_result.get('error', 'Failed to place bet')}", ephemeral=True)
            return
        
        game, error = create_coinflip_game(interaction.user.id, bet, side)
        if error:
            # Refund bet atomically
            await db.pay_from_budget_atomic(
                discord_id=interaction.user.id,
                gross_amount=bet,
                net_amount=bet,
                tax_amount=0,
                transaction_type=TransactionType.GAME_WIN,
                description="Coinflip bet refund"
            )
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
        # Note: flip() expects edge_chance as a percentage (0.5 == 0.5%).
        # The default must match config.json's documented format.
        edge_chance = game_config.get("edge_chance", 0.5)
        result = game.flip(edge_chance)
        
        if result == CoinflipResult.WIN:
            # Player wins - resolve ATOMICALLY
            profit_amount = game.winnings  # This is just the profit (equal to bet for 1:1)
            
            economy = await db.get_server_economy()
            
            # Resolve win atomically - pays back bet + profit (minus tax)
            win_result = await db.resolve_game_win_atomic(
                discord_id=interaction.user.id,
                bet_amount=bet,
                profit_amount=profit_amount,
                tax_rate=economy.tax_rate,
                description="Coinflip win"
            )
            
            if not win_result["success"]:
                await message.edit(content=f"❌ Error resolving win: {win_result.get('error')}")
                return
            
            total_payout = win_result["total_payout"]
            net_profit = win_result["net_profit"]
            tax = win_result["tax"]
            
            color = 0x00FF00
            result_text = f"🎉 **{game.result_side.upper()}** - YOU WIN!"
            profit = f"+{format_balance(net_profit)}"  # Show actual profit after tax
            
            # Log game
            await economy_logger.log_game(
                game_name="Coinflip",
                user_id=interaction.user.id,
                user_name=interaction.user.display_name,
                bet=bet,
                result=f"WIN ({game.result_side.upper()})",
                winnings=total_payout,
                profit=net_profit,
                user_before=user_before,
                user_after=win_result["after_balance"],
                budget_before=budget_before,
                budget_after=win_result["after_budget"],
                details={
                    "Choice": side.upper(),
                    "Landed On": game.result_side.upper(),
                    "Gross Profit": f"${profit_amount:,.2f}",
                    "Tax": f"${tax:,.2f}",
                    "Net Profit": f"${net_profit:,.2f}"
                }
            )
        elif result == CoinflipResult.EDGE:
            # Edge - money stays in server budget (already there from place_bet_atomic)
            color = 0x9B59B6
            result_text = "😱 **EDGE** - The coin landed on its edge!"
            profit = f"-{format_balance(bet)}"
            
            # Log game
            economy_after = await db.get_server_economy()
            await economy_logger.log_game(
                game_name="Coinflip",
                user_id=interaction.user.id,
                user_name=interaction.user.display_name,
                bet=bet,
                result="EDGE (0.5% chance!)",
                winnings=0,
                profit=-bet,
                user_before=user_before,
                user_after=user_before - bet,
                budget_before=budget_before,
                budget_after=economy_after.total_budget,
                details={"Choice": side.upper(), "Landed On": "EDGE"}
            )
        else:
            # Player loses - money stays in server budget (already there)
            color = 0xFF0000
            result_text = f"💔 **{game.result_side.upper()}** - YOU LOSE"
            profit = f"-{format_balance(bet)}"
            
            # Log game
            economy_after = await db.get_server_economy()
            await economy_logger.log_game(
                game_name="Coinflip",
                user_id=interaction.user.id,
                user_name=interaction.user.display_name,
                bet=bet,
                result=f"LOSS ({game.result_side.upper()})",
                winnings=0,
                profit=-bet,
                user_before=user_before,
                user_after=user_before - bet,
                budget_before=budget_before,
                budget_after=economy_after.total_budget,
                details={"Choice": side.upper(), "Landed On": game.result_side.upper()}
            )
        
        # Build clean result embed (no ANSI codes)
        embed = discord.Embed(
            title="🪙 COINFLIP - RESULT",
            description=f"**{result_text}**",
            color=color
        )
        embed.add_field(name="Your Choice", value=f"`{side.upper()}`", inline=True)
        embed.add_field(name="Result", value=f"`{game.result_side.upper() if game.result_side else 'EDGE'}`", inline=True)
        embed.add_field(name="Bet", value=f"`{format_balance(bet)}`", inline=True)
        embed.add_field(name="Profit/Loss", value=f"`{profit}`", inline=True)
        embed.set_footer(text=get_standard_footer())
        
        await message.edit(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesCog(bot))
