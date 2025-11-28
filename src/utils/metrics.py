"""
Prometheus Metrics for Monitoring
"""

from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server
from typing import Optional
import asyncio


class BotMetrics:
    """Prometheus metrics for the Discord bot"""
    
    def __init__(self):
        # Command metrics
        self.commands_total = Counter(
            "discord_commands_total",
            "Total number of commands executed",
            ["command", "status"]
        )
        
        self.command_latency = Histogram(
            "discord_command_latency_seconds",
            "Command execution latency",
            ["command"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        # Economy metrics
        self.transactions_total = Counter(
            "economy_transactions_total",
            "Total number of economic transactions",
            ["type"]
        )
        
        self.server_budget = Gauge(
            "server_budget_current",
            "Current server budget"
        )
        
        self.user_balance_sum = Gauge(
            "user_balance_sum",
            "Sum of all user balances"
        )
        
        self.taxes_collected = Counter(
            "economy_taxes_collected_total",
            "Total taxes collected"
        )
        
        # Game metrics
        self.games_active = Gauge(
            "games_active",
            "Number of active games",
            ["type"]
        )
        
        self.games_total = Counter(
            "games_total",
            "Total games played",
            ["type", "result"]
        )
        
        self.game_bets_total = Counter(
            "game_bets_total",
            "Total amount bet",
            ["type"]
        )
        
        # User metrics
        self.users_total = Gauge(
            "users_total",
            "Total registered users"
        )
        
        self.users_active = Gauge(
            "users_active",
            "Users active in last 24h"
        )
        
        self.voice_users = Gauge(
            "voice_users_current",
            "Users currently in voice channels"
        )
        
        # Rate limiting metrics
        self.rate_limit_hits = Counter(
            "rate_limit_hits_total",
            "Total rate limit violations",
            ["action"]
        )
        
        self.blacklist_events = Counter(
            "blacklist_events_total",
            "Total blacklist events",
            ["reason"]
        )
        
        # Security metrics
        self.security_events = Counter(
            "security_events_total",
            "Total security events",
            ["type", "severity"]
        )
        
        self.kicks_issued = Counter(
            "kicks_issued_total",
            "Total kicks issued",
            ["reason"]
        )
        
        # Bot health metrics
        self.bot_uptime = Gauge(
            "bot_uptime_seconds",
            "Bot uptime in seconds"
        )
        
        self.bot_latency = Gauge(
            "bot_latency_ms",
            "Discord API latency in milliseconds"
        )
        
        self.bot_guilds = Gauge(
            "bot_guilds_total",
            "Number of guilds the bot is in"
        )
        
        self.errors_total = Counter(
            "bot_errors_total",
            "Total bot errors",
            ["type"]
        )
        
        # Info metric
        self.bot_info = Info(
            "bot",
            "Bot information"
        )
        
        self._server_started = False
    
    def start_server(self, port: int = 8000) -> None:
        """Start Prometheus metrics server"""
        if not self._server_started:
            try:
                start_http_server(port)
                self._server_started = True
                print(f"Prometheus metrics server started on port {port}")
            except Exception as e:
                print(f"Failed to start Prometheus server: {e}")
    
    # Command tracking
    def track_command(self, command: str, status: str = "success") -> None:
        """Track command execution"""
        self.commands_total.labels(command=command, status=status).inc()
    
    def track_command_latency(self, command: str, latency: float) -> None:
        """Track command latency"""
        self.command_latency.labels(command=command).observe(latency)
    
    # Economy tracking
    def track_transaction(self, transaction_type: str) -> None:
        """Track economic transaction"""
        self.transactions_total.labels(type=transaction_type).inc()
    
    def update_server_budget(self, budget: float) -> None:
        """Update server budget gauge"""
        self.server_budget.set(budget)
    
    def update_user_balance_sum(self, total: float) -> None:
        """Update total user balance"""
        self.user_balance_sum.set(total)
    
    def track_tax(self, amount: float) -> None:
        """Track taxes collected"""
        self.taxes_collected.inc(amount)
    
    # Game tracking
    def set_active_games(self, game_type: str, count: int) -> None:
        """Set active game count"""
        self.games_active.labels(type=game_type).set(count)
    
    def track_game(self, game_type: str, result: str, bet: float) -> None:
        """Track game completion"""
        self.games_total.labels(type=game_type, result=result).inc()
        self.game_bets_total.labels(type=game_type).inc(bet)
    
    # User tracking
    def update_user_counts(self, total: int, active: int = 0) -> None:
        """Update user count gauges"""
        self.users_total.set(total)
        if active > 0:
            self.users_active.set(active)
    
    def update_voice_users(self, count: int) -> None:
        """Update voice users count"""
        self.voice_users.set(count)
    
    # Rate limit tracking
    def track_rate_limit(self, action: str) -> None:
        """Track rate limit hit"""
        self.rate_limit_hits.labels(action=action).inc()
    
    def track_blacklist(self, reason: str) -> None:
        """Track blacklist event"""
        self.blacklist_events.labels(reason=reason).inc()
    
    # Security tracking
    def track_security_event(self, event_type: str, severity: str) -> None:
        """Track security event"""
        self.security_events.labels(type=event_type, severity=severity).inc()
    
    def track_kick(self, reason: str) -> None:
        """Track kick issued"""
        self.kicks_issued.labels(reason=reason).inc()
    
    # Bot health tracking
    def update_uptime(self, seconds: float) -> None:
        """Update bot uptime"""
        self.bot_uptime.set(seconds)
    
    def update_latency(self, ms: float) -> None:
        """Update Discord latency"""
        self.bot_latency.set(ms)
    
    def update_guilds(self, count: int) -> None:
        """Update guild count"""
        self.bot_guilds.set(count)
    
    def track_error(self, error_type: str) -> None:
        """Track an error"""
        self.errors_total.labels(type=error_type).inc()
    
    def set_bot_info(self, **kwargs) -> None:
        """Set bot info"""
        self.bot_info.info(kwargs)


# Global metrics instance
metrics = BotMetrics()
