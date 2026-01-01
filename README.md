# JJI Bot

Discord bot for gaming community. Closed-loop economy, voice activity salaries, games, role shop.

## Setup

### Docker (recommended)
```bash
# Configure .env file
docker-compose up -d
```

### Local
```bash
pip install -r requirements.txt
alembic upgrade head
python bot.py
```

## Configuration

### .env
```
DISCORD_TOKEN=your_token
REDIS_URL=redis://localhost:6379
```

### config.json
```json
{
  "guild_id": 123456789,
  "channels": {
    "log_economy": 0,
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
  }
}
```

## Economy

**Principle:** Closed-loop. Money is never created from nothing or destroyed.

| Source | Direction |
|--------|-----------|
| Salary | Budget → User |
| Tax | Stays in budget |
| Soldier accepted | +soldier_value to budget |
| Soldier leaves | -soldier_value from budget |
| Game win | Budget → User |
| Game loss | User → Budget |
| Role purchase | User → Budget |
| Role sell | Budget → User (10%) |

### Salaries
- Distributed every minute during Prime Time (default: 14:00-22:00 UTC)
- 2x multiplier during Prime Time
- Muted users don't receive salary

## Commands

### Economy
| Command | Description |
|---------|-------------|
| `/balance` | Check balance |
| `/pay @user amount` | Transfer money |
| `/case` | Daily case (24h cooldown) |

### Games
| Command | Description |
|---------|-------------|
| `/blackjack bet` | Blackjack |
| `/coinflip bet side` | Coinflip |
| `/blackjack_pvp @user bet` | PvP blackjack |

### Shop
| Command | Description |
|---------|-------------|
| `/shop` | Browse roles |
| `/buy_role role` | Purchase role |
| `/sell_role role` | Sell role (10% refund) |
| `/myroles` | View owned roles |

### Officers
| Command | Description |
|---------|-------------|
| `/accept @user` | Accept recruit |
| `/officer_stats` | View stats |

### Admin
| Command | Description |
|---------|-------------|
| `/economy_panel` | Economy control panel |
| `/addbalance @user amount` | Add balance |
| `/fine @user amount` | Fine user |
| `/confiscate @user` | Confiscate balance |
| `/set_role type role` | Configure roles |
| `/set_log_channel type channel` | Configure channels |

## Structure

```
├── bot.py                 # Entry point
├── config.json            # Configuration
├── src/
│   ├── cogs/              # Commands
│   ├── services/          # DB, cache, logger
│   ├── models/            # SQLAlchemy models
│   ├── games/             # Game logic
│   └── utils/             # Helpers
├── alembic/               # Migrations
└── grafana/               # Dashboards
```

## Monitoring

- Prometheus: `localhost:8000`
- Grafana: `localhost:3000` (admin/admin)

## Development

```bash
# Tests
pytest tests/ -v

# Migration
alembic revision --autogenerate -m "description"
alembic upgrade head
```

---
Developed by NaveL for JJI © 2025
