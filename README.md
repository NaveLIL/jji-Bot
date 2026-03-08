# JJI Bot

A feature-rich Discord bot for gaming communities, built with **Python 3.11** and **discord.py 2.3+**. Implements a fully closed-loop economy, voice-activity salaries, casino games, a role shop, and comprehensive admin tooling.

## Key Features

- **Closed-Loop Economy** — Money is never created or destroyed. Every dollar flows between a central server budget and user wallets, tracked with atomic database transactions.
- **Voice Salary System** — Users earn salary every 10 minutes while in voice channels, with 2x Prime Time multiplier.
- **Casino Games** — Blackjack (solo + PvP) and Coinflip with split, double down, insurance, and surrender support.
- **Role Marketplace** — Admins add purchasable roles; users buy/sell with automatic budget accounting.
- **Officer Recruitment** — Officers can accept recruits, tracked with full stats and leaderboards.
- **Full Audit Logging** — Every economy action is logged with before/after balances and budget snapshots.
- **Monitoring** — Built-in Prometheus metrics + Grafana dashboards.

## Quick Start

### Docker (recommended)
```bash
cp .env.example .env   # Configure token & settings
docker-compose up -d
```

### Local
```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
alembic upgrade head
python bot.py
```

## Configuration

### `.env`
```env
DISCORD_TOKEN=your_bot_token
REDIS_URL=redis://localhost:6379
```

### `config.json`
```json
{
  "guild_id": 123456789,
  "channels": {
    "log_economy": 0,
    "log_officer": 0,
    "master_voice": 0,
    "ping_sergeant": 0
  },
  "roles": {
    "soldier": 0,
    "sergeant": 0,
    "officer": 0,
    "admin": 0
  },
  "prime_time": {
    "start_hour": 14,
    "end_hour": 22
  },
  "salaries": {
    "soldier_per_10min": 10,
    "sergeant_per_10min": 20,
    "officer_per_10min": 20,
    "sergeant_master_bonus": 50
  },
  "mute_penalty": {
    "enabled": true,
    "percentage": 50
  }
}
```

## Economy Model

**Principle:** Closed-loop. The total money supply (`ServerEconomy.total_budget` + sum of all user balances) is constant.

| Event | Flow |
|-------|------|
| Salary payout | Budget → User |
| Tax on transfers/wins | Stays in budget |
| Soldier accepted | +`soldier_value` to budget |
| Soldier leaves | −`soldier_value` from budget |
| Game bet placed | User → Budget |
| Game win | Budget → User (minus tax) |
| Game loss | Money stays in budget |
| Role purchase | User → Budget |
| Role sell | Budget → User (10% refund) |
| Mute penalty | User → Budget |
| Admin fine/confiscate | User → Budget |
| Admin addbalance | Budget → User |

### Salary Distribution
- Runs every minute, checks active voice sessions
- Rate determined by highest-paying role (Officer > Sergeant > Soldier)
- **Prime Time** (configurable, default 14:00–22:00 UTC): 2x multiplier
- Server-muted or timed-out users are skipped
- Tax is applied to salary before payout

## Commands (32 total)

### Economy
| Command | Description |
|---------|-------------|
| `/balance` | Check your current balance |
| `/pay @user amount` | Transfer money (taxed) |
| `/case` | Open a random case (24h cooldown) |
| `/daily` | Claim daily reward |

### Games
| Command | Description |
|---------|-------------|
| `/blackjack bet` | Play Blackjack against the dealer |
| `/coinflip bet side` | Heads or tails |
| `/blackjack_pvp @user bet` | PvP Blackjack challenge |

### Profile & Stats
| Command | Description |
|---------|-------------|
| `/profile [@user]` | View profile card |
| `/leaderboard` | Server leaderboard |
| `/stats` | Server economy statistics |

### Marketplace
| Command | Description |
|---------|-------------|
| `/shop` | Browse the role shop |
| `/inventory` | View your purchased roles |
| `/myroles` | View your roles |
| `/sellrole role` | Sell a role (10% refund) |
| `/addrole role price` | Add role to shop *(Admin)* |
| `/removerole role` | Remove role from shop *(Admin)* |

### Officers
| Command | Description |
|---------|-------------|
| `/accept @user` | Accept a recruit *(Officer)* |
| `/officer_stats` | View recruitment stats |
| `/recruits` | View your recruits *(Officer)* |

### Admin
| Command | Description |
|---------|-------------|
| `/economy_panel` | Economy control panel |
| `/setbalance @user amount` | Set user balance (budget-aware) |
| `/addbalance @user amount` | Add/remove balance (atomic) |
| `/fine @user amount` | Fine a user |
| `/confiscate @user` | Confiscate entire balance |
| `/set_log_channel type channel` | Configure log channels |
| `/set_master_channel channel` | Set master voice channel |
| `/set_ping_channel channel` | Set sergeant ping channel |
| `/set_role type role` | Configure system roles |
| `/set_user_rank @user rank` | Set user rank |
| `/about` | About this bot |
| `/botstats` | Bot statistics |
| `/sync_commands` | Sync slash commands |

## Project Structure

```
├── bot.py                      # Entry point, event handlers, salary task
├── config.json                 # Runtime configuration
├── docker-compose.yml          # Docker orchestration
├── Dockerfile                  # Python 3.11-slim image
├── requirements.txt            # Dependencies
├── alembic.ini                 # Migration config
├── alembic/                    # Database migrations
│   └── versions/
├── src/
│   ├── cogs/                   # Slash command groups
│   │   ├── admin.py            # Admin commands & economy panel
│   │   ├── economy.py          # Balance, pay, case, daily
│   │   ├── games.py            # Blackjack, Coinflip, PvP
│   │   ├── marketplace.py      # Role shop
│   │   ├── officer.py          # Recruitment system
│   │   └── profile.py          # Profile, leaderboard, stats
│   ├── games/                  # Pure game logic (no DB)
│   │   ├── blackjack.py        # Blackjack engine
│   │   └── coinflip.py         # Coinflip engine
│   ├── models/
│   │   └── database.py         # SQLAlchemy ORM models
│   ├── services/
│   │   ├── database.py         # All DB operations (atomic methods)
│   │   ├── cache.py            # Redis cache layer
│   │   └── economy_logger.py   # Structured economy logging
│   └── utils/
│       ├── helpers.py           # Tax calculation, formatting
│       ├── logger.py            # Logging configuration
│       ├── metrics.py           # Prometheus metrics
│       └── security.py          # Rate limiting, anti-abuse
├── tests/                       # Integration tests
│   ├── integration/
│   │   ├── test_atomicity.py
│   │   ├── test_concurrency.py
│   │   └── test_money_flow.py
├── grafana/                     # Monitoring dashboards
│   ├── dashboards/
│   └── provisioning/
└── docs/
    ├── ECONOMY_FLOW.md
    └── USER_GUIDE.md
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11 |
| Framework | discord.py >= 2.3.2 |
| Database | SQLite (aiosqlite) / PostgreSQL |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Cache | Redis 7 |
| Metrics | Prometheus |
| Dashboards | Grafana |
| Container | Docker + docker-compose |

## Monitoring

| Service | URL |
|---------|-----|
| Prometheus metrics | `http://localhost:8000` |
| Grafana dashboards | `http://localhost:3000` (admin/admin) |

## Development

```bash
# Run tests
pytest tests/ -v

# Create a new migration
alembic revision --autogenerate -m "description"
alembic upgrade head

# Sync slash commands manually
python -m src.scripts.sync_commands
```

## License

Developed by **NaveL** for JJI &copy; 2025–2026
