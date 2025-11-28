# JJI Regiment Discord Bot 🎖️

Production-grade Discord bot for military gaming community management.

## Features

- 💰 **Economy System** - Salaries based on voice activity, prime time bonuses
- 🎰 **Games** - 6-deck Blackjack with full rules, Coinflip with house edge
- 🛒 **Role Shop** - Buy, sell, and equip cosmetic roles
- 👮 **Officer Recruitment** - Track recruits with 10-hour bonus system
- 📊 **Monitoring** - Prometheus metrics + Grafana dashboards
- 🔒 **Security** - Rate limiting, anti-cheat, audit logging

## Tech Stack

- Python 3.11+
- discord.py 2.3+
- SQLAlchemy 2.0 (async) + Alembic migrations
- Redis for caching and session state
- Docker + docker-compose
- Prometheus + Grafana

## Quick Start

### Local Development

1. Clone the repository
2. Create virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy `.env.example` to `.env` and fill in your Discord token:
```bash
copy .env.example .env
```

5. Configure `config.json` with your server settings

6. Run migrations:
```bash
alembic upgrade head
```

7. Start the bot:
```bash
python bot.py
```

### Docker Deployment

1. Configure `.env` file
2. Start all services:
```bash
docker-compose up -d
```

3. Access Grafana at `http://localhost:3000` (default: admin/admin)
4. Access Prometheus at `http://localhost:9090`

## Configuration

### config.json

```json
{
  "guild_id": 123456789,
  "channels": {
    "log": 0,
    "master_voice": 0,
    "ping": 0
  },
  "roles": {
    "soldier": 0,
    "sergeant": 0,
    "officer": 0,
    "master": 0
  }
}
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Your Discord bot token |
| `DATABASE_URL` | SQLite/PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `LOG_CHANNEL_WEBHOOK` | Discord webhook for logging |

## Commands

### Economy
- `/balance` - Check your balance
- `/case` - Open daily case (24h cooldown)
- `/pay @user amount` - Transfer money to another user

### Profile
- `/profile [@user]` - View profile with stats
- `/leaderboard [type]` - View top users (balance/pb_time)

### Games
- `/blackjack bet` - Play blackjack (min $10)
- `/coinflip bet side` - Flip a coin (min $10)

### Marketplace
- `/shop` - Browse available roles
- `/buyrole role` - Purchase a role
- `/myroles` - Manage your purchased roles
- `/sellrole role` - Sell a role (50% refund)

### Officer
- `/accept @recruit` - Accept a new recruit
- `/officer_stats` - View your recruitment stats

### Admin
- `/economy_panel` - Open economy control panel
- `/set_log_channel` - Configure logging channel
- `/fine @user amount` - Fine a user
- `/confiscate @user` - Confiscate entire balance
- `/add_shop_role role price` - Add role to shop

## Economy System

### Salaries (per 10 minutes in voice)
- **Soldier**: $10
- **Sergeant**: $20 + $50 daily master bonus
- **Officer**: $20 + recruitment rewards

### Prime Time
- Hours: 14:00 - 22:00 UTC
- Bonus: 2x salary during prime time

### Tax System
- Default rate: 10%
- Applied to all transactions
- Collected taxes go to server budget

### Mute Penalty
- Muted users are not eligible for salary

## Games

### Blackjack
- 6-deck shoe, reshuffles at 75% penetration
- Dealer stands on soft 17
- Actions: Hit, Stand, Double, Split, Surrender
- Insurance on dealer Ace
- Blackjack pays 3:2

### Coinflip
- 50/50 odds with 0.5% house edge
- Animated coin flip
- Instant payout

## Officer Recruitment

1. Officer uses `/accept @recruit` in ping channel
2. Recruit receives Soldier role
3. Officer gets $20 immediate reward
4. If recruit stays 10+ hours in voice, officer gets $50 bonus
5. All recruitment activity is logged

## Security

- Rate limiting: 3 commands/min per user
- Game limits: 10 games/min per user
- Double-spend prevention
- Suspicious pattern detection
- All transactions are logged

## Monitoring

### Prometheus Metrics
- `jji_commands_total` - Command usage counter
- `jji_transactions_total` - Transaction counter
- `jji_games_active` - Active games gauge
- `jji_server_budget_current` - Server budget gauge
- `jji_user_balance_sum` - Total user balance sum

### Grafana Dashboard
Pre-configured dashboard available at `grafana/dashboards/jji_bot.json`

## Database Schema

- `users` - User accounts and balances
- `roles` - Shop roles
- `user_roles` - Purchased roles
- `transactions` - Transaction history
- `server_economy` - Server budget and stats
- `officer_logs` - Recruitment logs
- `channel_configs` - Channel settings
- `security_logs` - Security events

## Project Structure

```
JJI/
├── bot.py              # Main entry point
├── config.json         # Bot configuration
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker image
├── docker-compose.yml  # Docker services
├── alembic.ini         # Migration config
├── alembic/            # Database migrations
├── grafana/            # Grafana dashboards
├── src/
│   ├── models/         # SQLAlchemy models
│   ├── services/       # Database & Redis services
│   ├── games/          # Game engines
│   ├── cogs/           # Discord commands
│   └── utils/          # Helpers, logging, metrics
└── data/               # Database files
```

## Development

### Running Tests
```bash
pytest tests/ -v
```

### Creating Migration
```bash
alembic revision --autogenerate -m "description"
```

### Applying Migrations
```bash
alembic upgrade head
```

## License

Developed by NaveL for JJI Regiment © 2025
