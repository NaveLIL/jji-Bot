"""
Games Cog - Blackjack and Coinflip commands
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from typing import Literal

from src.services.database import db
from src.services.cache import cache
from src.models.database import TransactionType, GameType
from src.games.blackjack import create_blackjack_game, BlackjackGame, GameState
from src.games.coinflip import create_coinflip_game, CoinflipResult, CoinSide
from src.utils.helpers import format_balance, validate_bet, calculate_tax, load_config
from src.utils.security import rate_limited, game_rate_limited
from src.utils.metrics import metrics


class BlackjackView(discord.ui.View):
    """Interactive blackjack game view"""
    
    def __init__(self, game: BlackjackGame, cog: "GamesCog", timeout: float = 300):
        super().__init__(timeout=timeout)
        self.game = game
        self.cog = cog
        self.message: discord.Message = None
        self.update_buttons()
    
    def update_buttons(self):
        """Update button availability based on game state"""
        actions = self.game.get_available_actions()
        
        # Clear all buttons first
        self.clear_items()
        
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
        """Generate game embed"""
        data = self.game.get_display_embed_data()
        
        # Color based on state
        if self.game.is_complete:
            net = data["net_result"]
            if net > 0:
                color = discord.Color.green()
            elif net < 0:
                color = discord.Color.red()
            else:
                color = discord.Color.gold()
        else:
            color = discord.Color.blue()
        
        embed = discord.Embed(
            title="🃏 Blackjack",
            color=color
        )
        
        # Dealer section
        dealer_value = data["dealer_value"]
        embed.add_field(
            name=f"Dealer ({dealer_value})",
            value=data["dealer_cards"],
            inline=False
        )
        
        # Player hands
        for i, hand in enumerate(data["player_hands"]):
            hand_name = f"{'➡️ ' if hand['is_current'] else ''}Your Hand"
            if len(data["player_hands"]) > 1:
                hand_name += f" #{i+1}"
            
            hand_name += f" ({hand['value']})"
            
            embed.add_field(
                name=hand_name,
                value=f"{hand['cards']}\nBet: {hand['bet']}",
                inline=True
            )
        
        # Results
        if self.game.is_complete and data["results"]:
            results_text = []
            for i, (result, amount) in enumerate(data["results"]):
                prefix = f"Hand #{i+1}: " if len(data["results"]) > 1 else ""
                if amount > 0:
                    results_text.append(f"{prefix}✅ {result.upper()} +{format_balance(amount)}")
                elif amount < 0:
                    results_text.append(f"{prefix}❌ {result.upper()} {format_balance(amount)}")
                else:
                    results_text.append(f"{prefix}🤝 {result.upper()}")
            
            embed.add_field(
                name="Results",
                value="\n".join(results_text),
                inline=False
            )
            
            net = data["net_result"]
            if net > 0:
                embed.add_field(name="💰 Net Win", value=format_balance(net), inline=True)
            elif net < 0:
                embed.add_field(name="💸 Net Loss", value=format_balance(net), inline=True)
            else:
                embed.add_field(name="🤝 Push", value="No change", inline=True)
        
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        return embed
    
    async def on_timeout(self):
        """Handle timeout - auto-stand"""
        if not self.game.is_complete:
            while not self.game.is_complete:
                self.game.stand()
            
            await self.finish_game()
    
    async def finish_game(self):
        """Finish the game and update balance"""
        net_result = self.game.get_net_result()
        
        if net_result != 0:
            # Apply tax on winnings only
            if net_result > 0:
                config = load_config()
                economy = await db.get_server_economy()
                net_amount, tax = calculate_tax(net_result, economy.tax_rate)
                
                await db.update_user_balance(
                    self.game.user_id,
                    net_amount,
                    TransactionType.GAME_WIN,
                    tax_amount=tax,
                    description="Blackjack win"
                )
                
                if tax > 0:
                    await db.add_taxes_collected(tax)
                    metrics.track_tax(tax)
                
                metrics.track_game("blackjack", "win", self.game.bet)
            else:
                # No need to deduct - bet was already taken
                metrics.track_game("blackjack", "lose", self.game.bet)
        else:
            # Push - refund bet
            await db.update_user_balance(
                self.game.user_id,
                self.game.bet,
                TransactionType.GAME_WIN,
                description="Blackjack push - refund"
            )
            metrics.track_game("blackjack", "push", self.game.bet)
        
        # Delete game session
        await cache.delete_game_state(self.game.user_id, "blackjack")
        
        # Update message
        self.update_buttons()
        if self.message:
            try:
                await self.message.edit(embed=self.get_embed(), view=None)
            except Exception:
                pass
    
    async def update_game(self, interaction: discord.Interaction):
        """Update game display after action"""
        if self.game.is_complete:
            await self.finish_game()
            await interaction.response.edit_message(embed=self.get_embed(), view=None)
        else:
            # Save game state
            await cache.save_game_state(
                self.game.user_id,
                "blackjack",
                self.game.to_dict()
            )
            
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)


class HitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Hit", style=discord.ButtonStyle.primary, custom_id="bj:hit")
    
    async def callback(self, interaction: discord.Interaction):
        view: BlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        
        view.game.hit()
        await view.update_game(interaction)


class StandButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Stand", style=discord.ButtonStyle.secondary, custom_id="bj:stand")
    
    async def callback(self, interaction: discord.Interaction):
        view: BlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        
        view.game.stand()
        await view.update_game(interaction)


class DoubleButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Double", style=discord.ButtonStyle.success, custom_id="bj:double")
    
    async def callback(self, interaction: discord.Interaction):
        view: BlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        
        # Check balance for double
        user = await db.get_or_create_user(view.game.user_id)
        double_cost = view.game.current_hand.bet
        
        if user.balance < double_cost:
            await interaction.response.send_message(
                f"Insufficient balance to double! Need {format_balance(double_cost)}",
                ephemeral=True
            )
            return
        
        # Deduct additional bet
        await db.update_user_balance(
            view.game.user_id,
            -double_cost,
            TransactionType.GAME_LOSS,
            description="Blackjack double down"
        )
        
        view.game.double_down()
        await view.update_game(interaction)


class SplitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Split", style=discord.ButtonStyle.success, custom_id="bj:split")
    
    async def callback(self, interaction: discord.Interaction):
        view: BlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        
        # Check balance for split
        user = await db.get_or_create_user(view.game.user_id)
        split_cost = view.game.current_hand.bet
        
        if user.balance < split_cost:
            await interaction.response.send_message(
                f"Insufficient balance to split! Need {format_balance(split_cost)}",
                ephemeral=True
            )
            return
        
        # Deduct additional bet
        await db.update_user_balance(
            view.game.user_id,
            -split_cost,
            TransactionType.GAME_LOSS,
            description="Blackjack split"
        )
        
        view.game.split()
        await view.update_game(interaction)


class SurrenderButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Surrender", style=discord.ButtonStyle.danger, custom_id="bj:surrender")
    
    async def callback(self, interaction: discord.Interaction):
        view: BlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        
        view.game.surrender()
        
        # Refund half the bet
        refund = view.game.bet / 2
        await db.update_user_balance(
            view.game.user_id,
            refund,
            TransactionType.GAME_WIN,
            description="Blackjack surrender refund"
        )
        
        await view.update_game(interaction)


class InsuranceYesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Take Insurance", style=discord.ButtonStyle.success, custom_id="bj:ins_yes")
    
    async def callback(self, interaction: discord.Interaction):
        view: BlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        
        # Check balance for insurance
        user = await db.get_or_create_user(view.game.user_id)
        insurance_cost = view.game.bet / 2
        
        if user.balance < insurance_cost:
            await interaction.response.send_message(
                f"Insufficient balance for insurance! Need {format_balance(insurance_cost)}",
                ephemeral=True
            )
            return
        
        # Deduct insurance bet
        await db.update_user_balance(
            view.game.user_id,
            -insurance_cost,
            TransactionType.GAME_LOSS,
            description="Blackjack insurance"
        )
        
        view.game.take_insurance(True)
        await view.update_game(interaction)


class InsuranceNoButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="No Insurance", style=discord.ButtonStyle.secondary, custom_id="bj:ins_no")
    
    async def callback(self, interaction: discord.Interaction):
        view: BlackjackView = self.view
        if interaction.user.id != view.game.user_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return
        
        view.game.take_insurance(False)
        await view.update_game(interaction)


class GamesCog(commands.Cog):
    """Game commands"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = load_config()
    
    @app_commands.command(name="blackjack", description="Play blackjack!")
    @app_commands.describe(bet="Amount to bet (1-10000)")
    @game_rate_limited(cooldown_seconds=30)
    async def blackjack(self, interaction: discord.Interaction, bet: float):
        """Start a blackjack game"""
        # Check for existing game
        existing = await cache.get_game_state(interaction.user.id, "blackjack")
        if existing:
            await interaction.response.send_message(
                "❌ You already have an active blackjack game! Finish it first.",
                ephemeral=True
            )
            return
        
        # Validate bet
        user = await db.get_or_create_user(interaction.user.id)
        
        config = self.config.get("economy", {})
        min_bet = config.get("min_bet", 1)
        max_bet = config.get("max_bet", 10000)
        max_pct = config.get("max_bet_percentage", 100)
        
        is_valid, error = validate_bet(bet, user.balance, min_bet, max_bet, max_pct)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        # Deduct bet
        success, _, _ = await db.update_user_balance(
            interaction.user.id,
            -bet,
            TransactionType.GAME_LOSS,
            description="Blackjack bet"
        )
        
        if not success:
            await interaction.response.send_message(
                "❌ Failed to place bet. Please try again.",
                ephemeral=True
            )
            return
        
        # Create game
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
        
        # Save to cache
        await cache.save_game_state(interaction.user.id, "blackjack", game.to_dict())
        
        # Create view
        view = BlackjackView(game, self)
        
        # Check for immediate completion (blackjack)
        if game.is_complete:
            await view.finish_game()
            await interaction.response.send_message(embed=view.get_embed())
        else:
            await interaction.response.send_message(embed=view.get_embed(), view=view)
            view.message = await interaction.original_response()
        
        metrics.set_active_games("blackjack", 1)
    
    @app_commands.command(name="coinflip", description="Flip a coin!")
    @app_commands.describe(
        bet="Amount to bet (1-10000)",
        side="Choose heads or tails"
    )
    @game_rate_limited(cooldown_seconds=30)
    async def coinflip(
        self, 
        interaction: discord.Interaction, 
        bet: float,
        side: Literal["heads", "tails"]
    ):
        """Play coinflip"""
        # Validate bet
        user = await db.get_or_create_user(interaction.user.id)
        
        config = self.config.get("economy", {})
        min_bet = config.get("min_bet", 1)
        max_bet = config.get("max_bet", 10000)
        max_pct = config.get("max_bet_percentage", 100)
        
        is_valid, error = validate_bet(bet, user.balance, min_bet, max_bet, max_pct)
        if not is_valid:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        # Deduct bet
        success, _, _ = await db.update_user_balance(
            interaction.user.id,
            -bet,
            TransactionType.GAME_LOSS,
            description="Coinflip bet"
        )
        
        if not success:
            await interaction.response.send_message(
                "❌ Failed to place bet. Please try again.",
                ephemeral=True
            )
            return
        
        # Create game
        game, error = create_coinflip_game(interaction.user.id, bet, side)
        if error:
            # Refund bet
            await db.update_user_balance(
                interaction.user.id,
                bet,
                TransactionType.GAME_WIN,
                description="Coinflip bet refund"
            )
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        
        # Send initial message
        embed = discord.Embed(
            title="🪙 Coinflip",
            description=game.get_spin_frame(0),
            color=discord.Color.gold()
        )
        embed.add_field(name="Your Choice", value=side.upper(), inline=True)
        embed.add_field(name="Bet", value=format_balance(bet), inline=True)
        
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        
        # Animate
        game_config = self.config.get("games", {}).get("coinflip", {})
        edge_chance = game_config.get("edge_chance", 0.5)
        animation_duration = game_config.get("animation_duration", 3)
        
        frame_count = int(animation_duration / 0.5)
        
        for i in range(1, frame_count):
            embed.description = game.get_spin_frame(i)
            try:
                await message.edit(embed=embed)
            except Exception:
                pass
            await asyncio.sleep(0.5)
        
        # Flip and get result
        result = game.flip(edge_chance)
        
        # Determine color
        if result == CoinflipResult.WIN:
            color = discord.Color.green()
        elif result == CoinflipResult.EDGE:
            color = discord.Color.purple()
        else:
            color = discord.Color.red()
        
        # Process result
        if result == CoinflipResult.WIN:
            # Apply tax on winnings
            economy = await db.get_server_economy()
            net_amount, tax = calculate_tax(game.winnings, economy.tax_rate)
            
            # Add winnings + original bet back
            await db.update_user_balance(
                interaction.user.id,
                bet + net_amount,  # Return bet + net winnings
                TransactionType.GAME_WIN,
                tax_amount=tax,
                description="Coinflip win"
            )
            
            if tax > 0:
                await db.add_taxes_collected(tax)
                metrics.track_tax(tax)
            
            metrics.track_game("coinflip", "win", bet)
        else:
            # Loss - bet already deducted
            if result == CoinflipResult.EDGE:
                # Edge case - add to server budget
                await db.update_server_budget(bet)
                metrics.track_game("coinflip", "edge", bet)
            else:
                metrics.track_game("coinflip", "lose", bet)
        
        # Final embed
        embed = discord.Embed(
            title="🪙 Coinflip - Result!",
            description=game.get_result_display(),
            color=color
        )
        embed.add_field(name="Your Choice", value=side.upper(), inline=True)
        embed.add_field(name="Bet", value=format_balance(bet), inline=True)
        embed.set_footer(text="Developed by NaveL for JJI in 2025")
        
        try:
            await message.edit(embed=embed)
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesCog(bot))
