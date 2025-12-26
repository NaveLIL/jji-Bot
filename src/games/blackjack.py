"""
Blackjack Game Engine
Full-featured with 6-deck shoe, splits, doubles, insurance, surrender
Optimized for stability and PvP state management.
"""

import random
import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum

# --- Helper Functions (Mocked if src.utils.helpers is missing, but assuming you have them) ---
# If you actually need these implemented in this file, let me know. 
# For now, I assume they import correctly as per your original file.
from src.utils.helpers import (
    CARD_SUITS, CARD_RANKS,
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
    # PvP specific states
    WAITING = "waiting" # Waiting for opponent
    PLAYER_A_TURN = "player_a_turn"
    PLAYER_B_TURN = "player_b_turn"


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
        return cls(
            cards=[Card.from_dict(c) for c in data["cards"]],
            bet=data["bet"],
            is_doubled=data.get("is_doubled", False),
            is_split=data.get("is_split", False),
            is_stood=data.get("is_stood", False),
            is_surrendered=data.get("is_surrendered", False),
            insurance_bet=data.get("insurance_bet", 0.0)
        )
    
    def format_display(self, hide_first: bool = False) -> str:
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
        total_cards = self.deck_count * 52
        if total_cards == 0: return True
        dealt_ratio = self.dealt_count / total_cards
        return dealt_ratio >= self.penetration
    
    def draw(self) -> Card:
        """Draw a card from the shoe with safety checks"""
        if not self.cards or self.needs_shuffle():
            self._shuffle()
        
        if not self.cards: # Should be impossible unless deck_count=0
            self._shuffle()
            
        card = self.cards.pop()
        self.dealt_count += 1
        return card
    
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
    """Single Player Blackjack Game"""
    user_id: int
    bet: float
    shoe: Shoe
    player_hands: List[Hand] = field(default_factory=list)
    dealer_hand: Hand = field(default_factory=Hand)
    current_hand_index: int = 0
    state: GameState = GameState.BETTING
    results: List[Tuple[HandResult, float]] = field(default_factory=list)
    
    # Settings
    dealer_stands_soft_17: bool = True
    blackjack_payout: float = 1.5
    insurance_payout: float = 2.0
    max_splits: int = 3
    allow_ace_resplit: bool = False
    allow_surrender: bool = True
    
    # Metadata
    message_id: Optional[int] = None
    channel_id: Optional[int] = None
    
    @property
    def current_hand(self) -> Optional[Hand]:
        if 0 <= self.current_hand_index < len(self.player_hands):
            return self.player_hands[self.current_hand_index]
        return None
    
    @property
    def is_complete(self) -> bool:
        return self.state == GameState.COMPLETE

    @property
    def can_take_insurance(self) -> bool:
        if self.state != GameState.INSURANCE_OFFERED: return False
        if len(self.dealer_hand.cards) < 1: return False
        return self.dealer_hand.cards[0].rank == "A"

    def deal_initial(self) -> None:
        player_hand = Hand(bet=self.bet)
        
        # Deal: P, D, P, D
        player_hand.add_card(self.shoe.draw())
        self.dealer_hand.add_card(self.shoe.draw())
        player_hand.add_card(self.shoe.draw())
        self.dealer_hand.add_card(self.shoe.draw())
        
        self.player_hands = [player_hand]
        
        if self.dealer_hand.cards[0].rank == "A":
            self.state = GameState.INSURANCE_OFFERED
        else:
            self._check_initial_blackjacks()
            
    def _check_initial_blackjacks(self) -> None:
        player_bj = self.player_hands[0].is_blackjack
        dealer_bj = self.dealer_hand.is_blackjack
        
        if player_bj or dealer_bj:
            self.state = GameState.COMPLETE
            if player_bj and dealer_bj:
                self.results = [(HandResult.PUSH, 0)]
            elif player_bj:
                self.results = [(HandResult.BLACKJACK, self.bet * self.blackjack_payout)]
            else:
                self.results = [(HandResult.LOSE, -self.bet)]
        else:
            self.state = GameState.PLAYER_TURN

    def take_insurance(self, accept: bool) -> None:
        if not self.can_take_insurance: return
        
        insurance_cost = self.bet / 2
        if accept:
            self.player_hands[0].insurance_bet = insurance_cost
        
        if self.dealer_hand.is_blackjack:
            self.state = GameState.COMPLETE
            insurance_win = insurance_cost * self.insurance_payout if accept else 0
            
            if self.player_hands[0].is_blackjack:
                # Push main, win insurance
                self.results = [(HandResult.PUSH, insurance_win)]
            else:
                # Lose main, win insurance
                self.results = [(HandResult.LOSE, insurance_win - self.bet)]
        else:
            # Insurance lost (cost remains in hand.insurance_bet), game continues
            self._check_initial_blackjacks()

    def hit(self) -> Tuple[bool, Optional[Card]]:
        if self.state != GameState.PLAYER_TURN or not self.current_hand:
            return False, None
        
        card = self.shoe.draw()
        self.current_hand.add_card(card)
        
        if self.current_hand.is_bust:
            self._advance_hand()
            return True, card
            
        return False, card

    def stand(self) -> None:
        if self.state != GameState.PLAYER_TURN or not self.current_hand: return
        self.current_hand.is_stood = True
        self._advance_hand()

    def double_down(self) -> Tuple[bool, Optional[Card]]:
        if self.state != GameState.PLAYER_TURN or not self.current_hand: return False, None
        if not self.current_hand.can_double: return False, None
        
        self.current_hand.is_doubled = True
        card = self.shoe.draw()
        self.current_hand.add_card(card)
        self.current_hand.is_stood = True
        self._advance_hand()
        return True, card

    def split(self) -> bool:
        if self.state != GameState.PLAYER_TURN or not self.current_hand: return False
        if not self.current_hand.can_split: return False
        
        split_count = sum(1 for h in self.player_hands if h.is_split)
        if split_count >= self.max_splits: return False
        
        if self.current_hand.is_pair_of_aces and not self.allow_ace_resplit:
            if any(h.is_split and h.cards[0].rank == "A" for h in self.player_hands):
                return False

        original = self.current_hand
        card_moved = original.cards.pop()
        
        new_hand = Hand(bet=original.bet, is_split=True)
        new_hand.add_card(card_moved)
        original.is_split = True
        
        original.add_card(self.shoe.draw())
        new_hand.add_card(self.shoe.draw())
        
        self.player_hands.insert(self.current_hand_index + 1, new_hand)
        
        # Split Aces Logic: One card only, then auto-stand
        if card_moved.rank == "A":
            original.is_stood = True
            new_hand.is_stood = True
            self._advance_hand()
            
        return True

    def surrender(self) -> bool:
        if self.state != GameState.PLAYER_TURN: return False
        if not self.allow_surrender: return False
        if len(self.player_hands) != 1 or len(self.player_hands[0].cards) != 2: return False
        
        self.current_hand.is_surrendered = True
        self.state = GameState.COMPLETE
        self.results = [(HandResult.SURRENDER, -self.bet / 2)]
        return True

    def _advance_hand(self) -> None:
        # Try to find next playable hand
        for i in range(self.current_hand_index + 1, len(self.player_hands)):
            hand = self.player_hands[i]
            if not hand.is_stood and not hand.is_bust:
                self.current_hand_index = i
                return
        
        # No more hands, dealer's turn
        self.state = GameState.DEALER_TURN
        self._play_dealer()

    def _play_dealer(self) -> None:
        # If all player hands busted/surrendered, dealer doesn't need to draw
        active_hands = [h for h in self.player_hands if not h.is_bust and not h.is_surrendered]
        
        if active_hands:
            while True:
                val = self.dealer_hand.value
                is_soft = self.dealer_hand.is_soft
                if val > 17: break
                if val == 17:
                    if not is_soft or self.dealer_stands_soft_17: break
                
                # Safety valve for infinite loops
                if len(self.dealer_hand.cards) > 12: break 
                self.dealer_hand.add_card(self.shoe.draw())
        
        self.state = GameState.COMPLETE
        self._calculate_results()

    def _calculate_results(self) -> None:
        self.results = []
        dealer_val = self.dealer_hand.value
        dealer_bust = self.dealer_hand.is_bust
        
        for hand in self.player_hands:
            if hand.is_surrendered:
                self.results.append((HandResult.SURRENDER, -hand.bet / 2))
                continue
            if hand.is_bust:
                loss = hand.bet * 2 if hand.is_doubled else hand.bet
                self.results.append((HandResult.BUST, -loss))
                continue
                
            multiplier = 2 if hand.is_doubled else 1
            hand_val = hand.value
            
            if dealer_bust:
                self.results.append((HandResult.WIN, hand.bet * multiplier))
            elif hand_val > dealer_val:
                self.results.append((HandResult.WIN, hand.bet * multiplier))
            elif hand_val < dealer_val:
                self.results.append((HandResult.LOSE, -hand.bet * multiplier))
            else:
                self.results.append((HandResult.PUSH, 0))

    def to_dict(self) -> dict:
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
            # Settings
            "dealer_stands_soft_17": self.dealer_stands_soft_17,
            "blackjack_payout": self.blackjack_payout,
            "insurance_payout": self.insurance_payout,
            "max_splits": self.max_splits,
            "allow_ace_resplit": self.allow_ace_resplit,
            "allow_surrender": self.allow_surrender
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlackjackGame":
        game = cls(
            user_id=data["user_id"],
            bet=data["bet"],
            shoe=Shoe.from_dict(data["shoe"]),
            dealer_stands_soft_17=data.get("dealer_stands_soft_17", True),
            blackjack_payout=data.get("blackjack_payout", 1.5),
            insurance_payout=data.get("insurance_payout", 2.0),
            max_splits=data.get("max_splits", 3),
            allow_ace_resplit=data.get("allow_ace_resplit", False),
            allow_surrender=data.get("allow_surrender", True)
        )
        game.player_hands = [Hand.from_dict(h) for h in data["player_hands"]]
        game.dealer_hand = Hand.from_dict(data["dealer_hand"])
        game.current_hand_index = data["current_hand_index"]
        game.state = GameState(data["state"])
        game.results = [(HandResult(r[0]), r[1]) for r in data.get("results", [])]
        game.message_id = data.get("message_id")
        game.channel_id = data.get("channel_id")
        return game


@dataclass
class PvPBlackjackGame:
    """Improved PvP Blackjack engine.

    Fixes queue hangups and provides a Discord-friendly UI payload generator.
    """

    player_a_id: int
    player_b_id: int
    player_a_bet: float
    player_b_bet: float
    shoe: Shoe

    # State
    state: GameState = GameState.WAITING

    # Hands (lists because hands can be split)
    player_a_hands: List[Hand] = field(default_factory=list)
    player_b_hands: List[Hand] = field(default_factory=list)
    dealer_hand: Hand = field(default_factory=Hand)

    # Indexes for the currently played hand
    current_hand_index_a: int = 0
    current_hand_index_b: int = 0

    # Results mapping: player_id -> list of (HandResult, amount)
    results: Dict[int, List[Tuple[HandResult, float]]] = field(default_factory=dict)

    # Settings
    dealer_stands_soft_17: bool = True
    blackjack_payout: float = 1.5

    # Discord metadata
    message_id: Optional[int] = None
    channel_id: Optional[int] = None

    def deal_initial(self) -> None:
        """Deal initial cards and check for immediate dealer blackjack."""
        hand_a = Hand(bet=self.player_a_bet)
        hand_b = Hand(bet=self.player_b_bet)

        # Deal order: A, B, Dealer, A, B, Dealer
        hand_a.add_card(self.shoe.draw())
        hand_b.add_card(self.shoe.draw())
        self.dealer_hand.add_card(self.shoe.draw())

        hand_a.add_card(self.shoe.draw())
        hand_b.add_card(self.shoe.draw())
        self.dealer_hand.add_card(self.shoe.draw())

        self.player_a_hands = [hand_a]
        self.player_b_hands = [hand_b]

        # If dealer has blackjack the round ends immediately
        if self.dealer_hand.is_blackjack:
            self.state = GameState.COMPLETE
            self._resolve_results()
        else:
            # Start with Player A and immediately advance state
            self.state = GameState.PLAYER_A_TURN
            self._update_game_state()

    @property
    def current_turn_player_id(self) -> Optional[int]:
        """Return the discord id of the player whose turn it is now."""
        if self.state == GameState.PLAYER_A_TURN:
            return self.player_a_id
        if self.state == GameState.PLAYER_B_TURN:
            return self.player_b_id
        return None

    @property
    def current_active_hand(self) -> Optional[Hand]:
        """Return the Hand object currently awaiting player input."""
        if self.state == GameState.PLAYER_A_TURN:
            if 0 <= self.current_hand_index_a < len(self.player_a_hands):
                return self.player_a_hands[self.current_hand_index_a]
        if self.state == GameState.PLAYER_B_TURN:
            if 0 <= self.current_hand_index_b < len(self.player_b_hands):
                return self.player_b_hands[self.current_hand_index_b]
        return None

    def hit(self, user_id: int) -> Tuple[bool, Optional[Card]]:
        if user_id != self.current_turn_player_id:
            return False, None
        hand = self.current_active_hand
        if not hand:
            return False, None

        card = self.shoe.draw()
        hand.add_card(card)

        # If bust, advance the state immediately
        if hand.is_bust:
            self._update_game_state()
            return True, card

        # Auto-stand on 21 for smoother UI
        if hand.value == 21:
            hand.is_stood = True
            self._update_game_state()

        return False, card

    def stand(self, user_id: int) -> bool:
        if user_id != self.current_turn_player_id:
            return False
        hand = self.current_active_hand
        if not hand:
            return False

        hand.is_stood = True
        self._update_game_state()
        return True

    def double(self, user_id: int) -> Tuple[bool, Optional[Card]]:
        if user_id != self.current_turn_player_id:
            return False, None
        hand = self.current_active_hand
        if not hand or not hand.can_double:
            return False, None

        hand.is_doubled = True
        card = self.shoe.draw()
        hand.add_card(card)
        hand.is_stood = True
        self._update_game_state()
        return True, card

    def split(self, user_id: int) -> bool:
        if user_id != self.current_turn_player_id:
            return False
        hand = self.current_active_hand
        if not hand or not hand.can_split:
            return False

        original = hand
        card_moved = original.cards.pop()

        new_hand = Hand(bet=original.bet, is_split=True)
        new_hand.add_card(card_moved)
        original.is_split = True

        original.add_card(self.shoe.draw())
        new_hand.add_card(self.shoe.draw())

        is_aces = (card_moved.rank == "A")

        if user_id == self.player_a_id:
            self.player_a_hands.insert(self.current_hand_index_a + 1, new_hand)
            if is_aces:
                original.is_stood = True
                new_hand.is_stood = True
        else:
            self.player_b_hands.insert(self.current_hand_index_b + 1, new_hand)
            if is_aces:
                original.is_stood = True
                new_hand.is_stood = True

        self._update_game_state()
        return True

    def _update_game_state(self) -> None:
        """Main queue-checking loop. Finds the next playable hand and sets the state."""
        if self.state == GameState.COMPLETE:
            return

        # 1) Check Player A
        idx_a, done_a = self._find_next_playable(self.player_a_hands, self.current_hand_index_a)
        if not done_a:
            self.state = GameState.PLAYER_A_TURN
            self.current_hand_index_a = idx_a
            return

        # 2) Check Player B
        idx_b, done_b = self._find_next_playable(self.player_b_hands, self.current_hand_index_b)
        if not done_b:
            self.state = GameState.PLAYER_B_TURN
            self.current_hand_index_b = idx_b
            return

        # 3) Dealer's turn
        self.state = GameState.DEALER_TURN
        self._play_dealer()

    def _find_next_playable(self, hands: List[Hand], start_idx: int) -> Tuple[int, bool]:
        """Find the next hand index that requires action. Returns (index, all_done_bool)."""
        for i in range(start_idx, len(hands)):
            h = hands[i]
            if not h.is_bust and not h.is_stood and not h.is_blackjack:
                return i, False
        return len(hands) - 1, True

    def _play_dealer(self) -> None:
        # If both players have all busted, skip dealer draws
        all_a_bust = all(h.is_bust for h in self.player_a_hands)
        all_b_bust = all(h.is_bust for h in self.player_b_hands)

        if not (all_a_bust and all_b_bust):
            while True:
                val = self.dealer_hand.value
                is_soft = self.dealer_hand.is_soft

                if val > 17:
                    break
                if val == 17:
                    if not is_soft or self.dealer_stands_soft_17:
                        break

                if len(self.dealer_hand.cards) > 12:
                    break

                self.dealer_hand.add_card(self.shoe.draw())

        self.state = GameState.COMPLETE
        self._resolve_results()

    def _resolve_results(self) -> None:
        # PvP duel: compare hands head-to-head between Player A and Player B
        # For matching hand indices, decide winner between players directly.
        # For unmatched extra hands, fall back to comparing against dealer (legacy behaviour).

        dealer_val = self.dealer_hand.value
        dealer_bust = self.dealer_hand.is_bust
        dealer_bj = self.dealer_hand.is_blackjack

        def hand_base_bet(h: Hand) -> float:
            return h.bet * (2.0 if h.is_doubled else 1.0)

        def compare_to_dealer(h: Hand):
            # reuse previous single-player logic for fallback
            if h.is_bust:
                return (HandResult.BUST, -hand_base_bet(h))
            if h.is_blackjack:
                return (HandResult.PUSH, 0) if dealer_bj else (HandResult.BLACKJACK, hand_base_bet(h) * self.blackjack_payout)
            if dealer_bj:
                return (HandResult.LOSE, -hand_base_bet(h))
            if dealer_bust:
                return (HandResult.WIN, hand_base_bet(h))
            if h.value > dealer_val:
                return (HandResult.WIN, hand_base_bet(h))
            if h.value < dealer_val:
                return (HandResult.LOSE, -hand_base_bet(h))
            return (HandResult.PUSH, 0)

        a_results: List[Tuple[HandResult, float]] = []
        b_results: List[Tuple[HandResult, float]] = []

        max_hands = max(len(self.player_a_hands), len(self.player_b_hands))

        for i in range(max_hands):
            ha = self.player_a_hands[i] if i < len(self.player_a_hands) else None
            hb = self.player_b_hands[i] if i < len(self.player_b_hands) else None

            if ha and hb:
                # Both have a hand at this index -> compare head-to-head
                # Bust rules
                if ha.is_bust and hb.is_bust:
                    a_results.append((HandResult.BUST, -hand_base_bet(ha)))
                    b_results.append((HandResult.BUST, -hand_base_bet(hb)))
                    continue

                if ha.is_bust and not hb.is_bust:
                    a_results.append((HandResult.LOSE, -hand_base_bet(ha)))
                    b_results.append((HandResult.WIN, hand_base_bet(hb)))
                    continue

                if hb.is_bust and not ha.is_bust:
                    a_results.append((HandResult.WIN, hand_base_bet(ha)))
                    b_results.append((HandResult.LOSE, -hand_base_bet(hb)))
                    continue

                # Blackjacks
                if ha.is_blackjack and hb.is_blackjack:
                    a_results.append((HandResult.PUSH, 0))
                    b_results.append((HandResult.PUSH, 0))
                    continue
                if ha.is_blackjack and not hb.is_blackjack:
                    a_results.append((HandResult.BLACKJACK, hand_base_bet(ha) * self.blackjack_payout))
                    b_results.append((HandResult.LOSE, -hand_base_bet(hb)))
                    continue
                if hb.is_blackjack and not ha.is_blackjack:
                    a_results.append((HandResult.LOSE, -hand_base_bet(ha)))
                    b_results.append((HandResult.BLACKJACK, hand_base_bet(hb) * self.blackjack_payout))
                    continue

                # Regular comparison by value
                if ha.value > hb.value:
                    a_results.append((HandResult.WIN, hand_base_bet(ha)))
                    b_results.append((HandResult.LOSE, -hand_base_bet(hb)))
                elif ha.value < hb.value:
                    a_results.append((HandResult.LOSE, -hand_base_bet(ha)))
                    b_results.append((HandResult.WIN, hand_base_bet(hb)))
                else:
                    a_results.append((HandResult.PUSH, 0))
                    b_results.append((HandResult.PUSH, 0))

            elif ha and not hb:
                # Opponent has no corresponding hand -> compare this hand to dealer
                a_results.append(compare_to_dealer(ha))

            elif hb and not ha:
                b_results.append(compare_to_dealer(hb))

        self.results[self.player_a_id] = a_results
        self.results[self.player_b_id] = b_results

    # --- Discord-friendly visualization ---
    def get_discord_payload(self, player_a_name: str, player_b_name: str) -> dict:
        """Produce a ready-to-use payload for a Discord embed and available actions."""
        is_game_over = (self.state == GameState.COMPLETE)
        # Dealer display (hide hole card if game not over)
        if is_game_over:
            d_cards = " ".join(str(c) for c in self.dealer_hand.cards)
            d_val = "BUST" if self.dealer_hand.is_bust else str(self.dealer_hand.value)
            dealer_str = f"{d_cards}\nPoints: {d_val}"
        else:
            visible = self.dealer_hand.cards[1:]
            d_cards = "?? " + " ".join(str(c) for c in visible)
            dealer_str = f"{d_cards}\nPoints: ?"

        def format_player_field(name: str, hands: List[Hand], current_idx: int, is_active_turn: bool, result_list=None) -> str:
            lines = []
            for i, hand in enumerate(hands):
                label = f"Hand {i+1}:"
                active_marker = " <— Your turn" if is_active_turn and i == current_idx and not is_game_over else ""

                cards_str = " ".join(str(c) for c in hand.cards)
                val_str = f"{hand.value}"
                status_parts = []
                if hand.is_bust:
                    status_parts.append("BUST")
                elif hand.is_blackjack:
                    status_parts.append("BJ")
                if hand.is_doubled:
                    status_parts.append("x2")
                if hand.is_surrendered:
                    status_parts.append("Surrendered")

                if is_game_over and result_list:
                    res_type, amt = result_list[i]
                    if res_type == HandResult.WIN or res_type == HandResult.BLACKJACK:
                        status_parts.append(f"+${amt:.1f}")
                    elif res_type == HandResult.LOSE or res_type == HandResult.BUST:
                        status_parts.append(f"-${abs(amt):.1f}")
                    elif res_type == HandResult.PUSH:
                        status_parts.append("Push")

                status = (" — " + ", ".join(status_parts)) if status_parts else ""
                lines.append(f"{label} {cards_str} ({val_str}){status}{active_marker}")
            return "\n".join(lines)

        a_active = (self.state == GameState.PLAYER_A_TURN)
        b_active = (self.state == GameState.PLAYER_B_TURN)
        a_field = format_player_field(player_a_name, self.player_a_hands, self.current_hand_index_a, a_active, self.results.get(self.player_a_id))
        b_field = format_player_field(player_b_name, self.player_b_hands, self.current_hand_index_b, b_active, self.results.get(self.player_b_id))

        color = 0x2b2d31
        if a_active:
            color = 0x3498db
        elif b_active:
            color = 0xe91e63
        elif is_game_over:
            color = 0xf1c40f

        status_text = "Game in progress"
        if a_active:
            status_text = f"{player_a_name}'s Turn"
        elif b_active:
            status_text = f"{player_b_name}'s Turn"
        elif is_game_over:
            status_text = "Game complete"

        return {
            "embed": {
                "title": f"PvP Blackjack — {status_text}",
                "color": color,
                "fields": [
                    {"name": "Dealer", "value": dealer_str, "inline": False},
                    {"name": f"{player_a_name} (${self.player_a_bet})", "value": a_field or "—", "inline": False},
                    {"name": f"{player_b_name} (${self.player_b_bet})", "value": b_field or "—", "inline": False},
                ]
            },
            "actions": self.get_available_actions()
        }

    def get_available_actions(self) -> List[str]:
        if self.state == GameState.COMPLETE or self.state == GameState.DEALER_TURN:
            return []
        hand = self.current_active_hand
        if not hand:
            return []
        actions = ["hit", "stand"]
        if hand.can_double:
            actions.append("double")
        if hand.can_split:
            actions.append("split")
        return actions

    def to_dict(self) -> dict:
        return {
            "player_a_id": self.player_a_id,
            "player_b_id": self.player_b_id,
            "player_a_bet": self.player_a_bet,
            "player_b_bet": self.player_b_bet,
            "shoe": self.shoe.to_dict(),
            "state": self.state.value,
            "player_a_hands": [h.to_dict() for h in self.player_a_hands],
            "player_b_hands": [h.to_dict() for h in self.player_b_hands],
            "dealer_hand": self.dealer_hand.to_dict(),
            "current_hand_index_a": self.current_hand_index_a,
            "current_hand_index_b": self.current_hand_index_b,
            "results": {str(k): [(r[0].value, r[1]) for r in v] for k, v in self.results.items()},
            "message_id": self.message_id,
            "channel_id": self.channel_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PvPBlackjackGame":
        game = cls(
            player_a_id=data["player_a_id"],
            player_b_id=data["player_b_id"],
            player_a_bet=data["player_a_bet"],
            player_b_bet=data["player_b_bet"],
            shoe=Shoe.from_dict(data["shoe"])
        )
        game.state = GameState(data["state"])
        game.player_a_hands = [Hand.from_dict(h) for h in data.get("player_a_hands", [])]
        game.player_b_hands = [Hand.from_dict(h) for h in data.get("player_b_hands", [])]
        game.dealer_hand = Hand.from_dict(data.get("dealer_hand", {"cards": [], "bet": 0}))
        game.current_hand_index_a = data.get("current_hand_index_a", 0)
        game.current_hand_index_b = data.get("current_hand_index_b", 0)
        raw_res = data.get("results", {})
        game.results = {int(k): [(HandResult(r[0]), r[1]) for r in v] for k, v in raw_res.items()}
        game.message_id = data.get("message_id")
        game.channel_id = data.get("channel_id")
        return game


def create_blackjack_game(user_id: int, bet: float, deck_count: int = 6, **settings) -> BlackjackGame:
    """Helper to create a single-player BlackjackGame with a fresh shoe and initial deal."""
    shoe = Shoe(deck_count=deck_count)
    game = BlackjackGame(
        user_id=user_id,
        bet=bet,
        shoe=shoe,
        dealer_stands_soft_17=settings.get("dealer_stands_soft_17", True),
        blackjack_payout=settings.get("blackjack_payout", 1.5),
        insurance_payout=settings.get("insurance_payout", 2.0),
        max_splits=settings.get("max_splits", 3),
        allow_ace_resplit=settings.get("allow_ace_resplit", False),
        allow_surrender=settings.get("allow_surrender", True),
    )
    game.deal_initial()
    return game
 