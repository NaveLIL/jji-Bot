"""
Blackjack Game Engine
Full-featured with 6-deck shoe, splits, doubles, insurance, surrender
"""

import random
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple
from enum import Enum

from src.utils.helpers import (
    CARD_SUITS, CARD_RANKS, CARD_VALUES,
    calculate_hand_value, is_soft_hand, is_blackjack,
    can_split, can_double, format_hand
)


class GameState(str, Enum):
    """Blackjack game states"""
    BETTING = "betting"
    PLAYER_TURN = "player_turn"
    DEALER_TURN = "dealer_turn"
    INSURANCE_OFFERED = "insurance"
    COMPLETE = "complete"


class HandResult(str, Enum):
    """Hand outcome results"""
    WIN = "win"
    LOSE = "lose"
    PUSH = "push"
    BLACKJACK = "blackjack"
    BUST = "bust"
    SURRENDER = "surrender"


@dataclass
class Card:
    """Represents a playing card"""
    rank: str
    suit: str
    
    def to_dict(self) -> dict:
        return {"rank": self.rank, "suit": self.suit}
    
    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(rank=data["rank"], suit=data["suit"])
    
    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"


@dataclass
class Hand:
    """Represents a blackjack hand"""
    cards: List[Card] = field(default_factory=list)
    bet: float = 0.0
    is_doubled: bool = False
    is_split: bool = False
    is_stood: bool = False
    is_surrendered: bool = False
    insurance_bet: float = 0.0
    
    @property
    def value(self) -> int:
        return calculate_hand_value([c.to_dict() for c in self.cards])
    
    @property
    def is_soft(self) -> bool:
        return is_soft_hand([c.to_dict() for c in self.cards])
    
    @property
    def is_blackjack(self) -> bool:
        return is_blackjack([c.to_dict() for c in self.cards]) and not self.is_split
    
    @property
    def is_bust(self) -> bool:
        return self.value > 21
    
    @property
    def can_split(self) -> bool:
        return can_split([c.to_dict() for c in self.cards]) and not self.is_split
    
    @property
    def can_double(self) -> bool:
        return can_double([c.to_dict() for c in self.cards]) and not self.is_doubled
    
    @property
    def is_pair_of_aces(self) -> bool:
        return len(self.cards) == 2 and all(c.rank == "A" for c in self.cards)
    
    def add_card(self, card: Card) -> None:
        self.cards.append(card)
    
    def to_dict(self) -> dict:
        return {
            "cards": [c.to_dict() for c in self.cards],
            "bet": self.bet,
            "is_doubled": self.is_doubled,
            "is_split": self.is_split,
            "is_stood": self.is_stood,
            "is_surrendered": self.is_surrendered,
            "insurance_bet": self.insurance_bet
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Hand":
        hand = cls(
            cards=[Card.from_dict(c) for c in data["cards"]],
            bet=data["bet"],
            is_doubled=data.get("is_doubled", False),
            is_split=data.get("is_split", False),
            is_stood=data.get("is_stood", False),
            is_surrendered=data.get("is_surrendered", False),
            insurance_bet=data.get("insurance_bet", 0.0)
        )
        return hand
    
    def format_display(self, hide_first: bool = False) -> str:
        """Format hand for Discord display"""
        if hide_first and len(self.cards) > 1:
            return f"[🂠] {format_hand([c.to_dict() for c in self.cards[1:]])}"
        return format_hand([c.to_dict() for c in self.cards])


class Shoe:
    """Multi-deck shoe for blackjack"""
    
    def __init__(self, deck_count: int = 6, penetration: float = 0.75):
        self.deck_count = deck_count
        self.penetration = penetration
        self.cards: List[Card] = []
        self.dealt_count = 0
        self._shuffle()
    
    def _shuffle(self) -> None:
        """Create and shuffle the shoe"""
        self.cards = []
        for _ in range(self.deck_count):
            for suit in CARD_SUITS:
                for rank in CARD_RANKS:
                    self.cards.append(Card(rank=rank, suit=suit))
        
        random.shuffle(self.cards)
        self.dealt_count = 0
    
    def needs_shuffle(self) -> bool:
        """Check if shoe needs reshuffling based on penetration"""
        total_cards = self.deck_count * 52
        dealt_ratio = self.dealt_count / total_cards
        return dealt_ratio >= self.penetration
    
    def draw(self) -> Card:
        """Draw a card from the shoe"""
        if not self.cards or self.needs_shuffle():
            self._shuffle()
        
        card = self.cards.pop()
        self.dealt_count += 1
        return card
    
    def remaining(self) -> int:
        """Get remaining cards in shoe"""
        return len(self.cards)
    
    def to_dict(self) -> dict:
        return {
            "deck_count": self.deck_count,
            "penetration": self.penetration,
            "cards": [c.to_dict() for c in self.cards],
            "dealt_count": self.dealt_count
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Shoe":
        shoe = cls(
            deck_count=data["deck_count"],
            penetration=data["penetration"]
        )
        shoe.cards = [Card.from_dict(c) for c in data["cards"]]
        shoe.dealt_count = data["dealt_count"]
        return shoe


@dataclass
class BlackjackGame:
    """Complete blackjack game state"""
    user_id: int
    bet: float
    shoe: Shoe
    player_hands: List[Hand] = field(default_factory=list)
    dealer_hand: Hand = field(default_factory=Hand)
    current_hand_index: int = 0
    state: GameState = GameState.BETTING
    results: List[Tuple[HandResult, float]] = field(default_factory=list)
    message_id: Optional[int] = None
    channel_id: Optional[int] = None
    
    # Game settings
    dealer_stands_soft_17: bool = True
    blackjack_payout: float = 1.5
    insurance_payout: float = 2.0
    max_splits: int = 3
    allow_ace_resplit: bool = False
    allow_surrender: bool = True
    
    @property
    def current_hand(self) -> Optional[Hand]:
        if 0 <= self.current_hand_index < len(self.player_hands):
            return self.player_hands[self.current_hand_index]
        return None
    
    @property
    def total_bet(self) -> float:
        """Calculate total amount bet including splits and doubles"""
        total = 0.0
        for hand in self.player_hands:
            total += hand.bet
            if hand.is_doubled:
                total += hand.bet  # Double adds another bet
            total += hand.insurance_bet
        return total
    
    @property
    def is_complete(self) -> bool:
        return self.state == GameState.COMPLETE
    
    @property
    def can_take_insurance(self) -> bool:
        """Check if insurance is available"""
        if self.state != GameState.INSURANCE_OFFERED:
            return False
        if len(self.dealer_hand.cards) < 1:
            return False
        return self.dealer_hand.cards[0].rank == "A"
    
    def deal_initial(self) -> None:
        """Deal initial cards"""
        # Create player's first hand
        player_hand = Hand(bet=self.bet)
        
        # Deal: Player, Dealer, Player, Dealer
        player_hand.add_card(self.shoe.draw())
        self.dealer_hand.add_card(self.shoe.draw())
        player_hand.add_card(self.shoe.draw())
        self.dealer_hand.add_card(self.shoe.draw())
        
        self.player_hands = [player_hand]
        
        # Check for dealer Ace (insurance opportunity)
        if self.dealer_hand.cards[0].rank == "A":
            self.state = GameState.INSURANCE_OFFERED
        else:
            self._check_initial_blackjacks()
    
    def _check_initial_blackjacks(self) -> None:
        """Check for initial blackjacks and set game state"""
        player_bj = self.player_hands[0].is_blackjack
        dealer_bj = self.dealer_hand.is_blackjack
        
        if player_bj or dealer_bj:
            self.state = GameState.COMPLETE
            
            if player_bj and dealer_bj:
                self.results = [(HandResult.PUSH, 0)]
            elif player_bj:
                winnings = self.bet * self.blackjack_payout
                self.results = [(HandResult.BLACKJACK, winnings)]
            else:
                self.results = [(HandResult.LOSE, -self.bet)]
        else:
            self.state = GameState.PLAYER_TURN
    
    def take_insurance(self, accept: bool) -> None:
        """Handle insurance decision"""
        if not self.can_take_insurance:
            return
        
        if accept:
            # Insurance costs half the bet
            self.player_hands[0].insurance_bet = self.bet / 2
        
        # Check for dealer blackjack
        if self.dealer_hand.is_blackjack:
            self.state = GameState.COMPLETE
            
            # Insurance pays 2:1 if dealer has blackjack
            insurance_payout = self.player_hands[0].insurance_bet * self.insurance_payout if accept else 0
            
            if self.player_hands[0].is_blackjack:
                # Push on main bet, win insurance
                self.results = [(HandResult.PUSH, insurance_payout)]
            else:
                # Lose main bet, but insurance pays
                net = insurance_payout - self.bet - (self.bet / 2 if accept else 0)
                self.results = [(HandResult.LOSE, net)]
        else:
            # No dealer blackjack, insurance loses if taken
            if accept:
                # Insurance lost
                pass
            self._check_initial_blackjacks()
    
    def hit(self) -> Tuple[bool, Card]:
        """Hit current hand. Returns (is_bust, card_drawn)"""
        if self.state != GameState.PLAYER_TURN or not self.current_hand:
            return False, None
        
        card = self.shoe.draw()
        self.current_hand.add_card(card)
        
        if self.current_hand.is_bust:
            self._advance_to_next_hand()
            return True, card
        
        return False, card
    
    def stand(self) -> None:
        """Stand on current hand"""
        if self.state != GameState.PLAYER_TURN or not self.current_hand:
            return
        
        self.current_hand.is_stood = True
        self._advance_to_next_hand()
    
    def double_down(self) -> Tuple[bool, Optional[Card]]:
        """Double down on current hand. Returns (success, card_drawn)"""
        if self.state != GameState.PLAYER_TURN or not self.current_hand:
            return False, None
        
        if not self.current_hand.can_double:
            return False, None
        
        self.current_hand.is_doubled = True
        card = self.shoe.draw()
        self.current_hand.add_card(card)
        
        # After double, automatically stand
        self.current_hand.is_stood = True
        self._advance_to_next_hand()
        
        return True, card
    
    def split(self) -> bool:
        """Split current hand. Returns success."""
        if self.state != GameState.PLAYER_TURN or not self.current_hand:
            return False
        
        if not self.current_hand.can_split:
            return False
        
        # Check max splits
        split_count = sum(1 for h in self.player_hands if h.is_split)
        if split_count >= self.max_splits:
            return False
        
        # Check ace resplit
        if self.current_hand.is_pair_of_aces and not self.allow_ace_resplit:
            if any(h.is_split and h.cards[0].rank == "A" for h in self.player_hands):
                return False
        
        # Perform split
        original = self.current_hand
        card = original.cards.pop()  # Remove second card
        
        # Create new hand
        new_hand = Hand(bet=original.bet, is_split=True)
        new_hand.add_card(card)
        
        original.is_split = True
        
        # Deal new cards to each hand
        original.add_card(self.shoe.draw())
        new_hand.add_card(self.shoe.draw())
        
        # Insert new hand after current
        self.player_hands.insert(self.current_hand_index + 1, new_hand)
        
        # For split aces, only one card each and auto-stand
        if card.rank == "A":
            original.is_stood = True
            new_hand.is_stood = True
            self._advance_to_next_hand()
        
        return True
    
    def surrender(self) -> bool:
        """Surrender current hand. Returns success."""
        if self.state != GameState.PLAYER_TURN:
            return False
        
        if not self.allow_surrender:
            return False
        
        # Can only surrender on initial hand (2 cards, no splits)
        if len(self.player_hands) != 1 or len(self.player_hands[0].cards) != 2:
            return False
        
        self.current_hand.is_surrendered = True
        self.state = GameState.COMPLETE
        
        # Surrender loses half bet
        self.results = [(HandResult.SURRENDER, -self.bet / 2)]
        return True
    
    def _advance_to_next_hand(self) -> None:
        """Move to next hand or dealer turn"""
        # Find next playable hand
        for i in range(self.current_hand_index + 1, len(self.player_hands)):
            hand = self.player_hands[i]
            if not hand.is_stood and not hand.is_bust:
                self.current_hand_index = i
                return
        
        # No more player hands, check if all busted
        all_bust = all(h.is_bust or h.is_surrendered for h in self.player_hands)
        
        if all_bust:
            self.state = GameState.COMPLETE
            self._calculate_results()
        else:
            self.state = GameState.DEALER_TURN
            self._play_dealer()
    
    def _play_dealer(self) -> None:
        """Play out dealer's hand"""
        while True:
            value = self.dealer_hand.value
            is_soft = self.dealer_hand.is_soft
            
            # Dealer stands on 17+ (or soft 17 based on rules)
            if value > 17:
                break
            if value == 17:
                if not is_soft or self.dealer_stands_soft_17:
                    break
            
            self.dealer_hand.add_card(self.shoe.draw())
        
        self.state = GameState.COMPLETE
        self._calculate_results()
    
    def _calculate_results(self) -> None:
        """Calculate final results for all hands"""
        self.results = []
        dealer_value = self.dealer_hand.value
        dealer_bust = self.dealer_hand.is_bust
        
        for hand in self.player_hands:
            if hand.is_surrendered:
                self.results.append((HandResult.SURRENDER, -hand.bet / 2))
                continue
            
            if hand.is_bust:
                loss = hand.bet * 2 if hand.is_doubled else hand.bet
                self.results.append((HandResult.BUST, -loss))
                continue
            
            player_value = hand.value
            multiplier = 2 if hand.is_doubled else 1
            
            if dealer_bust:
                self.results.append((HandResult.WIN, hand.bet * multiplier))
            elif player_value > dealer_value:
                self.results.append((HandResult.WIN, hand.bet * multiplier))
            elif player_value < dealer_value:
                self.results.append((HandResult.LOSE, -hand.bet * multiplier))
            else:
                self.results.append((HandResult.PUSH, 0))
    
    def get_net_result(self) -> float:
        """Get total net result (winnings - losses - insurance)"""
        total = sum(r[1] for r in self.results)
        
        # Subtract insurance bets if no payout
        for hand in self.player_hands:
            if hand.insurance_bet > 0:
                # Insurance only pays on dealer BJ, which is handled earlier
                if not self.dealer_hand.is_blackjack:
                    total -= hand.insurance_bet
        
        return total
    
    def get_available_actions(self) -> List[str]:
        """Get list of available actions for current state"""
        actions = []
        
        if self.state == GameState.INSURANCE_OFFERED:
            return ["insurance_yes", "insurance_no"]
        
        if self.state != GameState.PLAYER_TURN or not self.current_hand:
            return actions
        
        actions.extend(["hit", "stand"])
        
        if self.current_hand.can_double:
            actions.append("double")
        
        if self.current_hand.can_split:
            split_count = sum(1 for h in self.player_hands if h.is_split)
            if split_count < self.max_splits:
                actions.append("split")
        
        if self.allow_surrender and len(self.player_hands) == 1 and len(self.current_hand.cards) == 2:
            actions.append("surrender")
        
        return actions
    
    def get_display_embed_data(self) -> dict:
        """Get data for Discord embed display"""
        dealer_hidden = self.state in [GameState.PLAYER_TURN, GameState.INSURANCE_OFFERED]
        
        # Format dealer hand
        if dealer_hidden:
            dealer_display = self.dealer_hand.format_display(hide_first=True)
            dealer_value = "?"
        else:
            dealer_display = self.dealer_hand.format_display()
            dealer_value = str(self.dealer_hand.value)
            if self.dealer_hand.is_bust:
                dealer_value = "BUST"
        
        # Format player hands
        hands_display = []
        for i, hand in enumerate(self.player_hands):
            prefix = "➡️ " if i == self.current_hand_index and self.state == GameState.PLAYER_TURN else ""
            value = hand.value
            value_str = "BUST" if hand.is_bust else str(value)
            
            if hand.is_soft and value <= 21:
                value_str = f"{value} (soft)"
            
            bet_info = f"${hand.bet:.0f}"
            if hand.is_doubled:
                bet_info = f"${hand.bet * 2:.0f} (doubled)"
            
            hands_display.append({
                "prefix": prefix,
                "cards": hand.format_display(),
                "value": value_str,
                "bet": bet_info,
                "is_current": i == self.current_hand_index,
                "is_split": hand.is_split
            })
        
        return {
            "dealer_cards": dealer_display,
            "dealer_value": dealer_value,
            "player_hands": hands_display,
            "state": self.state.value,
            "actions": self.get_available_actions(),
            "results": [(r[0].value, r[1]) for r in self.results] if self.results else None,
            "net_result": self.get_net_result() if self.is_complete else None
        }
    
    def to_dict(self) -> dict:
        """Serialize game state to dictionary"""
        return {
            "user_id": self.user_id,
            "bet": self.bet,
            "shoe": self.shoe.to_dict(),
            "player_hands": [h.to_dict() for h in self.player_hands],
            "dealer_hand": self.dealer_hand.to_dict(),
            "current_hand_index": self.current_hand_index,
            "state": self.state.value,
            "results": [(r[0].value, r[1]) for r in self.results],
            "message_id": self.message_id,
            "channel_id": self.channel_id,
            "dealer_stands_soft_17": self.dealer_stands_soft_17,
            "blackjack_payout": self.blackjack_payout,
            "insurance_payout": self.insurance_payout,
            "max_splits": self.max_splits,
            "allow_ace_resplit": self.allow_ace_resplit,
            "allow_surrender": self.allow_surrender
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "BlackjackGame":
        """Deserialize game state from dictionary"""
        game = cls(
            user_id=data["user_id"],
            bet=data["bet"],
            shoe=Shoe.from_dict(data["shoe"])
        )
        game.player_hands = [Hand.from_dict(h) for h in data["player_hands"]]
        game.dealer_hand = Hand.from_dict(data["dealer_hand"])
        game.current_hand_index = data["current_hand_index"]
        game.state = GameState(data["state"])
        game.results = [(HandResult(r[0]), r[1]) for r in data.get("results", [])]
        game.message_id = data.get("message_id")
        game.channel_id = data.get("channel_id")
        game.dealer_stands_soft_17 = data.get("dealer_stands_soft_17", True)
        game.blackjack_payout = data.get("blackjack_payout", 1.5)
        game.insurance_payout = data.get("insurance_payout", 2.0)
        game.max_splits = data.get("max_splits", 3)
        game.allow_ace_resplit = data.get("allow_ace_resplit", False)
        game.allow_surrender = data.get("allow_surrender", True)
        return game
    
    def to_json(self) -> str:
        """Serialize to JSON string"""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> "BlackjackGame":
        """Deserialize from JSON string"""
        return cls.from_dict(json.loads(json_str))


def create_blackjack_game(
    user_id: int,
    bet: float,
    deck_count: int = 6,
    penetration: float = 0.75,
    **settings
) -> BlackjackGame:
    """Create a new blackjack game"""
    shoe = Shoe(deck_count=deck_count, penetration=penetration)
    
    game = BlackjackGame(
        user_id=user_id,
        bet=bet,
        shoe=shoe,
        dealer_stands_soft_17=settings.get("dealer_stands_soft_17", True),
        blackjack_payout=settings.get("blackjack_payout", 1.5),
        insurance_payout=settings.get("insurance_payout", 2.0),
        max_splits=settings.get("max_splits", 3),
        allow_ace_resplit=settings.get("allow_ace_resplit", False),
        allow_surrender=settings.get("allow_surrender", True)
    )
    
    game.deal_initial()
    return game
