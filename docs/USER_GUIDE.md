# JJI Squad Bot - Complete User Guide

> **Your complete guide to the JJI Economy & Gaming Bot**

---

## 📖 Table of Contents

1. [Getting Started](#getting-started)
2. [Economy System](#economy-system)
3. [Profile & Leaderboards](#profile--leaderboards)
4. [Casino Games](#casino-games)
5. [Role Shop (Marketplace)](#role-shop-marketplace)
6. [Officer System](#officer-system)
7. [SB Time (Voice Activity) Tracking](#sb-time-voice-activity-tracking)
8. [Administration Guide](#administration-guide)
9. [FAQ](#faq)

---

## 🚀 Getting Started

Welcome to **JJI Squad Bot** — a complete closed-loop economy system for the JJI gaming community. This bot features:

- 💰 **Economy System** — Earn, transfer, and manage your virtual currency
- 🎮 **Casino Games** — Play Blackjack and Coinflip to win (or lose) money
- 🛒 **Role Shop** — Buy cosmetic color and name roles
- 👮 **Officer Recruitment** — Officers earn rewards for recruiting new members
- ⏱️ **SB Time Tracking** — Earn salary for time spent in voice channels

### Important Concepts

| Term | Description |
|------|-------------|
| **Balance** | Your personal wallet amount |
| **Server Budget** | The total money pool for the entire server |
| **Tax** | A percentage taken from most transactions that returns to the server budget |
| **SB Time** | Time spent in voice channels (tracked for salary purposes) |
| **Prime Time** | Special hours when salaries are **2x** (configured by admins) |

---

## 💰 Economy System

### Checking Your Balance

**Command:** `/balance`

Shows your current balance, including:
- Your total money
- Your rank on the leaderboard
- Your total SB time
- Number of roles you own

---

### Transferring Money

**Command:** `/pay @user [amount]`

Transfer money to another user.

| Parameter | Description |
|-----------|-------------|
| `@user` | The person you want to pay |
| `amount` | How much to send |

**Important Notes:**
- A **tax** is deducted from the transfer (e.g., 10%)
- The recipient receives the amount **after tax**
- Tax returns to the server budget
- You cannot pay yourself or bots

**Example:**
- You send `$100` with 10% tax
- Tax taken: `$10`
- Recipient receives: `$90`
- Your balance decreases by: `$100`

---

### Daily Case (Free Reward)

**Commands:** `/case` or `/daily`

Open a daily case with a chance to win money!

**How it works:**
- **24-hour cooldown** between uses
- **30% chance** of empty case (no reward)
- **70% chance** to win money with tiered rewards:
  - **Low tier** (60% chance): $1-5
  - **Medium tier** (30% chance): $6-15
  - **High tier** (10% chance): $16-50

**Note:** All winnings are subject to tax. The timer shows when your next case is available.

---

## 👤 Profile & Leaderboards

### Viewing Profiles

**Command:** `/profile [@user]`

View your profile or another user's profile.

**Shows:**
- Balance and rank
- SB time and rank
- Number of owned roles
- Badges: Officer 👮, Sergeant 🎖️, Soldier ⚔️
- Join date

---

### Leaderboard

**Command:** `/leaderboard [type]`

View the server rankings.

| Type | Description |
|------|-------------|
| `balance` | Rank by money (default) |
| `pb_time` | Rank by voice channel time |

**Features:**
- Paginated (use ◀ ▶ buttons)
- Top 3 get special highlighting 🥇🥈🥉
- Refresh button to update live

---

### Server Statistics

**Command:** `/stats`

View overall server economy statistics:
- Server budget (treasury)
- Current tax rate
- Total users
- Total user balances combined
- Total taxes collected
- Total rewards paid
- Complete economy value

---

## 🎮 Casino Games

### ⚠️ Important Gambling Rules

- All winnings are **taxed** (tax goes to server budget)
- **Bet limits** are configured by admins (default: $1 - $10,000)
- Games have **cooldowns** to prevent spam
- **House edge exists** — the house (server budget) has a small advantage
- Gamble responsibly!

---

### 🃏 Blackjack (vs Dealer)

**Command:** `/blackjack [bet]`

Classic casino Blackjack against the dealer.

**Objective:** Get closer to 21 than the dealer without going over.

**Card Values:**
| Card | Value |
|------|-------|
| 2-10 | Face value |
| J, Q, K | 10 |
| Ace | 1 or 11 (whichever is better) |

**Actions:**

| Button | Action | Description |
|--------|--------|-------------|
| 🎴 HIT | Draw a card | Take another card |
| 🛑 STAND | Stop | Keep your current hand |
| 💰 DOUBLE | Double down | Double your bet, get one more card, then stand |
| ✂️ SPLIT | Split pairs | If you have two cards of same value, split into two hands |
| 🏳️ SURRENDER | Give up | Forfeit half your bet (first action only) |

**Special Rules:**
- **Blackjack** (Ace + 10-value on first deal) pays **1.5x** your bet
- **Dealer stands on soft 17**
- **Push** (tie) — your bet is returned
- You can split up to 3 times

**Tips:**
- Stand on 17+ against dealer 2-6
- Hit on 16 or less against dealer 7+
- Always split Aces and 8s
- Never split 10s or 5s
- Double on 11 against dealer 2-10

**After Game Options:**
- 🔁 **Play Again** — Start new game with same bet
- 💎 **Double or Nothing** — Risk your winnings for double
- ❌ **Quit** — Close the game

---

### ⚔️ PvP Blackjack (vs Another Player)

**Command:** `/blackjack_pvp @opponent [bet]`

Challenge another player to a Blackjack duel!

**How it works:**
1. You send a challenge to your opponent
2. They have 60 seconds to **ACCEPT** or **DECLINE**
3. Both players bet the same amount
4. Player A plays first, then Player B
5. Hands are compared — best hand wins!
6. Winner takes the opponent's bet (minus tax)

**Rules:**
- Both players must have enough balance
- Same card rules as regular Blackjack
- No dealer — you compete against each other
- In case of tie, bets are returned

---

### 🪙 Coinflip

**Command:** `/coinflip [bet] [side]`

Simple coin flip betting.

| Parameter | Options |
|-----------|---------|
| `bet` | Amount to wager |
| `side` | `heads` or `tails` |

**How it works:**
- Pick heads or tails
- 50/50 chance (with tiny house edge)
- Win = **2x your bet** (minus tax)
- Lose = lose your bet

**Example:**
- Bet $100 on heads
- If heads: Win $200 (minus tax)
- If tails: Lose $100

---

## 🛒 Role Shop (Marketplace)

### Opening the Shop

**Command:** `/shop`

Opens an interactive shop with two tabs:

| Tab | Description |
|-----|-------------|
| 🎨 **Colors** | Cosmetic color roles (change your name color) |
| 📛 **Names** | Special name badge roles |

---

### Buying Roles

1. Open `/shop`
2. Click on **🎨 Colors** or **📛 Names** tab
3. Select a role from the dropdown
4. Confirm purchase

**Rules:**
- **Color Roles:** You can only have **1** at a time (buying a new one replaces the old)
- **Name Roles:** You can own up to **5** name roles
- **Tax is applied** on purchases
- Prices vary per role

---

### Viewing Your Inventory

**Command:** `/myroles` or click **🎒 Inventory** in shop

See all roles you own and their status.

---

### Selling Roles

1. Go to **🎒 Inventory** in the shop
2. Select a role from the dropdown
3. Confirm sale

**Refund:** You get **10%** of the original price back.

---

## 👮 Officer System

*This section is for members with the Officer role.*

### Accepting Recruits

**Command:** `/accept @recruit`

Accept a new member into the squad.

**What happens:**
1. The recruit gets the **Soldier** role
2. Their **Guest** role is removed
3. You earn a **recruitment reward** (e.g., $50)
4. The recruit is added to your tracking list

**Requirements:**
- You must have the **Officer** role
- The recruit cannot already be a Soldier
- Server budget must have enough to pay your reward

---

### Viewing Your Recruits

**Command:** `/recruits`

See your last 10 recruits and their progress:
- ⏳ Progress towards 10h SB bonus
- ✅ Bonus already claimed
- 🎁 Bonus ready to claim!

---

### Officer Statistics

**Command:** `/officer_stats [@officer]`

View recruitment statistics:
- Total recruits accepted
- Pending 10h bonuses
- Claimed bonuses
- Lifetime earnings breakdown

**Note:** Viewing another officer's stats requires admin or Guest Admin role.

---

## ⏱️ SB Time (Voice Activity) Tracking

### How Salaries Work

When you're in a voice channel, you earn money over time!

**Salary Rates (per 10 minutes):**
| Role | Base Rate | Prime Time (2x) |
|------|-----------|-----------------|
| Soldier | $10 | $20 |
| Sergeant | $20 | $40 |
| Officer | $20 | $40 |

**Prime Time:** Special hours (set by admins, e.g., 14:00-22:00 UTC) when salaries are doubled!

### How It's Tracked

- Automatically tracked when you join voice channels
- Payments are made periodically (every 10 minutes)
- Must be in a valid voice channel (not AFK)

### Viewing Your SB Stats

Use `/profile` to see your total accumulated SB time.

---

## 🔧 Administration Guide

*This section is for server administrators only.*

### Economy Control Panel

**Command:** `/economy_panel`

Opens a comprehensive dashboard with:

**Display Information:**
- Current server budget
- Tax rate
- Soldier value
- Users in voice (with role breakdown)
- Current salary rates
- Budget runway forecast
- Prime time status

**Configuration Buttons:**

| Button | Function |
|--------|----------|
| **Tax Rate** | Set the server-wide tax percentage (0-100%) |
| **Soldier Value** | Set the value added to budget per new soldier |
| **Prime Time** | Configure 2x salary hours (UTC) |
| **Salaries** | Set salary rates for each role |
| **Rewards** | Configure officer accept/bonus rewards |
| **Set Budget** | Set the server budget to a specific amount |
| **Add Budget** | Add money to the server budget |
| **📜 History** | View recent admin actions |
| **🎮 Games** | View today's gambling statistics |
| **🔄 Refresh** | Update the panel with current data |

---

### Direct Admin Commands

#### Adding/Setting Balance

**Command:** `/addbalance @user [amount]`

Add money to a user's balance.
- Positive amounts are **deducted from server budget**
- Negative amounts are **added to server budget**

**Command:** `/setbalance @user [amount]`

Set a user's balance to a specific amount.

---

#### Penalties

**Command:** `/fine @user [amount]`

Issue a fine to a user.
- Money is removed from user
- Money is added to server budget
- Logged as a fine

**Command:** `/confiscate @user`

Confiscate a user's **entire balance**.
- All money goes to server budget
- Use for rule violations

---

### Channel Configuration

**Command:** `/set_log_channel [type] #channel`

Set logging channels for different events.

| Type | Logs |
|------|------|
| `officer` | Officer actions (accepts, bonuses) |
| `recruit` | New recruit notifications |
| `economy` | Economy transactions |
| `games` | Game results |
| `server` | Server events |
| `security` | Security alerts, suspicious activity |

**Command:** `/set_master_channel #voice-channel`

Set the master voice channel for salary tracking.

**Command:** `/set_ping_channel #channel`

Set the channel for sergeant pings.

---

### FAQ/Reference System

Create interactive FAQ panels with searchable dropdown menus. Panels persist across bot restarts.

#### Panel Management

| Command | Description |
|---------|-------------|
| `/faq create` | Create a new FAQ panel (opens modal) |
| `/faq list` | List all FAQ panels in the server |
| `/faq edit [panel_name]` | Edit panel title, description, color, footer |
| `/faq delete [panel_name]` | Delete a panel and all its entries |
| `/faq publish [panel_name] [channel]` | Publish panel to a channel |
| `/faq preview [panel_name]` | Preview panel before publishing |

#### Entry Management

| Command | Description |
|---------|-------------|
| `/faq entry add [panel_name]` | Add an entry to a panel (opens modal) |
| `/faq entry list [panel_name]` | List all entries in a panel |
| `/faq entry edit [entry_id]` | Edit an entry's label, content, emoji |
| `/faq entry delete [entry_id]` | Delete an entry |
| `/faq entry reorder [panel_name] [entry_id] [position]` | Reorder entries |

**How it works:**
1. Create a panel with `/faq create`
2. Add entries with `/faq entry add`
3. Preview with `/faq preview`
4. Publish with `/faq publish`

Users select topics from a dropdown menu and receive ephemeral (private) responses.

---

### About / Help Panel

**Command:** `/about`

Shows an interactive help panel with:
- 🏠 Overview — Bot features and status
- 💰 Economy — All economy commands
- 🎮 Games — Casino game information
- 👮 Officers — Officer system details
- ⚙️ Admin — Administration commands

---

## ❓ FAQ

### General Questions

**Q: Where does money come from?**
A: The server has a fixed budget. Money flows between the budget and users through salaries, rewards, and gambling. This is a "closed-loop" system — total money never increases or decreases.

**Q: What is tax used for?**
A: Tax returns to the server budget, ensuring the economy stays balanced. Without tax, money would only flow out of the budget.

**Q: How do I earn money?**
A: Several ways:
1. `/case` or `/daily` — Free daily reward
2. Stay in voice channels — Earn salary
3. Win at games — Gambling (risky!)
4. Receive payments — Other users can `/pay` you
5. Officer recruitment — Get paid for accepting recruits

---

### Gambling Questions

**Q: Is gambling fair?**
A: Games have a small house edge (advantage for the server). Blackjack uses standard casino rules. Over time, the house (server budget) will profit slightly.

**Q: Why was tax taken from my winnings?**
A: All income (including gambling wins) is taxed. This keeps money flowing back to the server budget.

**Q: What happens if I disconnect during a game?**
A: Blackjack games will auto-complete (you'll stand on your current hand). Your bet is not refunded.

---

### Role Shop Questions

**Q: Can I have multiple color roles?**
A: No, only one color role at a time. Buying a new one replaces your current one.

**Q: What's the refund when I sell a role?**
A: You get **10%** of the original purchase price back.

---

### Officer Questions

**Q: When do I get the 10h SB bonus?**
A: When a recruit you accepted reaches 10 hours of total voice time, you can claim a bonus. Check `/recruits` for progress.

**Q: Can I accept anyone?**
A: Only members who don't already have the Soldier role.

---

### Technical Questions

**Q: Commands aren't working!**
A: Try these steps:
1. Make sure you have the right permissions
2. Check if you're rate-limited (too many commands)
3. Wait a few seconds and try again
4. Contact an administrator

**Q: My balance seems wrong!**
A: All transactions are logged. Ask an admin to check the economy logs. Tax may explain discrepancies.

---

## 📞 Support

If you have questions not covered in this guide:
1. Ask in the server's help channel
2. Contact an Officer or Administrator
3. Use `/about` for quick command reference

---

*JJI Squad Bot — Building the community together!* 🎮
