#!/bin/bash
# Server update script for JJI Bot

# Stop on error
set -e

echo "🔄 Starting update process..."

# 1. Pull latest changes
echo "📥 Pulling from repository..."
git pull

# 2. Rebuild and restart containers
echo "🐳 Rebuilding and restarting containers..."
# Using --build to force rebuild of the bot image
# Using --remove-orphans to clean up any old service containers
docker compose up -d --build --remove-orphans

# 3. Clean up unused images (optional, saves space)
echo "🧹 Cleaning up old images..."
docker image prune -f

echo "✅ Update complete! Containers status:"
docker compose ps
