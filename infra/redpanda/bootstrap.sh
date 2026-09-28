#!/usr/bin/env bash
# One-shot Kafka security setup (docker compose service `redpanda-init`).
#   1. an admin user, 2. one user per service, 3. the topics,
#   4. the permissions in acls.conf, 5. switch on authentication.
# Safe to re-run: every step skips what already exists.
set -euo pipefail

BROKER="${REDPANDA_BROKER:-redpanda:9092}"
ADMIN_API="${REDPANDA_ADMIN_API:-redpanda:9644}"
MECH="SCRAM-SHA-256"
DIR="$(cd "$(dirname "$0")" && pwd)"

rpk_admin() { rpk "$@" -X admin.hosts="$ADMIN_API"; }

# Kafka-API commands need the admin login once authentication is on.
rpk_kafka() {
  if [ "$(rpk_admin cluster config get enable_sasl)" = "true" ]; then
    rpk "$@" -X brokers="$BROKER" -X user=admin -X pass="$KAFKA_ADMIN_PASSWORD" -X sasl.mechanism="$MECH"
  else
    rpk "$@" -X brokers="$BROKER"
  fi
}

create_user() {  # user password
  if rpk_admin security user list | awk 'NR>1 {print $1}' | grep -qx "$1"; then
    rpk_admin security user update "$1" --new-password "$2" --mechanism "$MECH" >/dev/null
  else
    rpk_admin security user create "$1" -p "$2" --mechanism "$MECH" >/dev/null
  fi
  echo "  user $1"
}

echo "[1/5] admin user"
create_user admin "$KAFKA_ADMIN_PASSWORD"
rpk_admin cluster config set superusers "['admin']" >/dev/null

echo "[2/5] service users"
create_user document-vendor-agent    "$KAFKA_PASSWORD_DOCUMENT_VENDOR_AGENT"
create_user approval-inventory-agent "$KAFKA_PASSWORD_APPROVAL_INVENTORY_AGENT"
create_user contract-risk-agent      "$KAFKA_PASSWORD_CONTRACT_RISK_AGENT"
create_user notification-agent       "$KAFKA_PASSWORD_NOTIFICATION_AGENT"
create_user auth-service             "$KAFKA_PASSWORD_AUTH_SERVICE"
create_user kafka-exporter           "$KAFKA_PASSWORD_KAFKA_EXPORTER"

echo "[3/5] topics (services can't create topics themselves)"
existing="$(rpk_kafka topic list | awk 'NR>1 {print $1}')"
for topic in $(grep -E '^\s*-\s' "$DIR/kafka-topics.yaml" | sed -E 's/^\s*-\s*//'); do
  if ! grep -qx "$topic" <<<"$existing"; then
    partitions=1; [ "$topic" = "document.ingested" ] && partitions=6
    rpk_kafka topic create "$topic" -p "$partitions" >/dev/null
    echo "  created $topic ($partitions partitions)"
  fi
done

echo "[4/5] permissions from acls.conf"
grep -vE '^\s*(#|$)' "$DIR/acls.conf" | while read -r user permission resource name; do
  case "$resource" in
    topic)   target=(--topic "$name") ;;
    group)   target=(--group "$name") ;;
    cluster) target=(--cluster) ;;
  esac
  rpk_kafka security acl create --allow-principal "User:$user" --operation "$permission" "${target[@]}" >/dev/null
done
echo "  $(grep -cvE '^\s*(#|$)' "$DIR/acls.conf") rules"

echo "[5/5] require authentication"
rpk_admin cluster config set enable_sasl true >/dev/null
echo "Kafka security ready."
