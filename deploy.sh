#!/bin/bash

# PrintBot Deploy Script
# Run on Runner PC: pulls latest from GitHub, rebuilds Docker image, restarts container

set -e

REPO_PATH="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_FILE="$REPO_PATH/logs/deploy.log"

mkdir -p "$REPO_PATH/logs"

{
    echo "=========================================="
    echo "PrintBot Deploy — $(date)"
    echo "=========================================="
    
    # Change to repo directory
    cd "$REPO_PATH"
    
    # Pull latest from GitHub
    echo "[1/4] Pulling from GitHub..."
    git pull origin main
    if [ $? -ne 0 ]; then
        echo "ERROR: Git pull failed"
        exit 1
    fi
    
    # Update .env if .env.example changed
    if [ ! -f ".env" ]; then
        echo "[2/4] Creating .env from template..."
        cp .env.example .env
        echo "⚠️  .env created — please edit with your configuration"
        echo "⚠️  Halting deployment until .env is configured"
        exit 1
    fi
    
    # Rebuild Docker images
    echo "[3/4] Rebuilding Docker image..."
    docker-compose build --no-cache
    if [ $? -ne 0 ]; then
        echo "ERROR: Docker build failed"
        exit 1
    fi
    
    # Restart containers
    echo "[4/4] Restarting containers..."
    docker-compose down
    docker-compose up -d
    if [ $? -ne 0 ]; then
        echo "ERROR: Docker compose up failed"
        exit 1
    fi
    
    # Check health
    sleep 5
    echo ""
    echo "Checking health..."
    curl -s http://localhost:8000/health | jq . || echo "Health check pending..."
    
    echo ""
    echo "✓ Deploy complete — $(date)"
    echo "View logs: docker-compose logs -f printbot"
    
} | tee -a "$LOG_FILE"

exit 0
