#!/bin/bash
#
# Deployment Verifier - Post-Deploy Health Checker
# Runs after deployment to verify system health
# Usage: ./deployment-verifier.sh [--hook] [--manual]
#
# Checks:
#   1. /healthz endpoint returns 200 OK
#   2. All docker containers show 'healthy' or 'Up' status
#
# On failure: sends alert to Gastown dashboard via gt_mail_send
#

set -euo pipefail

# Configuration
BACKEND_URL="${BACKEND_URL:-http://localhost}"
DOCKER_COMPOSE_FILE="${DOCKER_COMPOSE_FILE:-docker-compose.yml}"
ALERT_RECIPIENT="${ALERT_RECIPIENT:-rig_dashboard}"
DEPLOYMENT_ID="${DEPLOYMENT_ID:-$(date +%Y%m%d-%H%M%S)}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILURES=()

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

send_alert() {
    local subject="$1"
    local body="$2"

    echo "DEPLOYMENT VERIFICATION FAILED: $subject"
    echo "Details: $body"

    # Try to send alert to Gastown dashboard if gt_mail_send is available
    if command -v gt_mail_send &> /dev/null; then
        gt_mail_send --to "$ALERT_RECIPIENT" --subject "$subject" --body "$body" 2>/dev/null || true
    fi

    # Also write to a state file for dashboard pickup
    echo "$(date -Iseconds)|FAILED|$subject|$body" >> /tmp/deployment-verification.log
}

check_healthz() {
    log_info "Checking /healthz endpoint..."

    local http_code
    local max_retries=3
    local retry=0

    while [ $retry -lt $max_retries ]; do
        http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 "$BACKEND_URL/healthz" 2>/dev/null || echo "000")

        if [ "$http_code" = "200" ]; then
            log_info "Health check passed: HTTP $http_code"
            return 0
        fi

        retry=$((retry + 1))
        if [ $retry -lt $max_retries ]; then
            log_warn "Health check returned HTTP $http_code, retrying ($retry/$max_retries)..."
            sleep 2
        fi
    done

    log_error "Health check failed: expected HTTP 200, got HTTP $http_code"
    FAILURES+=("Health endpoint returned HTTP $http_code instead of 200")
    return 1
}

check_docker_containers() {
    log_info "Checking Docker container health..."

    local compose_dir=""
    if [ -f "$DOCKER_COMPOSE_FILE" ]; then
        compose_dir="."
    elif [ -f "federation-game/$DOCKER_COMPOSE_FILE" ]; then
        compose_dir="federation-game"
    else
        log_warn "Docker compose file not found at $DOCKER_COMPOSE_FILE"
        FAILURES+=("Docker compose file not found")
        return 1
    fi

    # Get container status
    local container_output
    container_output=$(cd "$compose_dir" && docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || docker-compose ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null || echo "")

    if [ -z "$container_output" ]; then
        log_error "Could not get container status"
        FAILURES+=("Could not query docker compose ps")
        return 1
    fi

    log_info "Container status:\n$container_output"

    # Check each container for unhealthy states
    local unhealthy=0
    while IFS= read -r line; do
        # Skip header lines
        if [[ "$line" =~ ^Name || "$line" =~ ^--- ]]; then
            continue
        fi

        # Check for container name and status
        if [[ "$line" =~ (Exited|unhealthy|starting|Restarting) ]]; then
            local container_name
            container_name=$(echo "$line" | awk '{print $1}')
            log_error "Container $container_name is not healthy: $line"
            FAILURES+=("Container $container_name status: $line")
            unhealthy=$((unhealthy + 1))
        fi
    done <<< "$container_output"

    if [ $unhealthy -gt 0 ]; then
        log_error "Found $unhealthy unhealthy containers"
        return 1
    fi

    log_info "All containers are healthy"
    return 0
}

check_required_services() {
    log_info "Checking required services..."

    local required_services=("backend" "postgres" "redis")

    for service in "${required_services[@]}"; do
        if ! docker compose ps --services 2>/dev/null | grep -q "^${service}$"; then
            log_warn "Required service $service not found in docker compose"
            FAILURES+=("Required service $service not found in docker compose")
        fi
    done
}

print_summary() {
    echo ""
    echo "================================"
    echo "Deployment Verification Summary"
    echo "================================"
    echo "Deployment ID: $DEPLOYMENT_ID"
    echo "Timestamp: $(date -Iseconds)"
    echo ""

    if [ ${#FAILURES[@]} -eq 0 ]; then
        echo -e "${GREEN}STATUS: PASSED${NC}"
        echo "All health checks passed successfully."
        return 0
    else
        echo -e "${RED}STATUS: FAILED${NC}"
        echo ""
        echo "Failures detected:"
        for i in "${!FAILURES[@]}"; do
            echo "  $((i+1)). ${FAILURES[$i]}"
        done
        return 1
    fi
}

main() {
    local mode="${1:---manual}"

    log_info "Starting deployment verification (mode: $mode)"
    log_info "Deployment ID: $DEPLOYMENT_ID"
    log_info "Backend URL: $BACKEND_URL"

    # Run checks
    check_healthz || true
    check_docker_containers || true
    check_required_services || true

    # Print summary and handle failures
    if ! print_summary; then
        # Send consolidated alert for all failures
        local failure_details
        failure_details=$(printf "  - %s\n" "${FAILURES[@]}")
        send_alert "DEPLOYMENT VERIFICATION FAILED" "Deployment $DEPLOYMENT_ID failed verification:\n$failure_details"
        exit 1
    fi

    exit 0
}

# Run main function
main "$@"