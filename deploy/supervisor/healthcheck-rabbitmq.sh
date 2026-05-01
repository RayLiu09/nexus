#!/usr/bin/env bash
set -Eeuo pipefail

rabbitmq-diagnostics -q ping >/dev/null
rabbitmq-diagnostics -q check_running >/dev/null
