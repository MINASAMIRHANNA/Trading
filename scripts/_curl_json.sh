#!/usr/bin/env bash
set -euo pipefail

# Shared curl helpers for smoke scripts.
#
# Exposes:
#   curl_capture <url> [extra curl args]
#     - prints body to stdout (may be empty)
#     - sets CURL_LAST_CODE to HTTP status (or 0 on network error)
#     - returns 0 on successful request, non-zero on curl failure
#
#   curl_json <url> [extra curl args]
#     - like curl_capture, but treats HTTP >=400 or code==0 as error,
#       prints diagnostics to stderr and returns non-zero.

CURL_LAST_CODE=0

curl_capture() {
  local url="$1"; shift || true
  local tmp out rc
  tmp="$(mktemp)"

  # Avoid `set -e` killing the caller before we can print diagnostics.
  set +e
  out=$(curl -sS -L --connect-timeout 3 --max-time 15     -o "$tmp" -w "%{http_code}"     "$@" "$url" 2>&1)
  rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    CURL_LAST_CODE=0
    echo "[curl] ERROR calling $url" >&2
    echo "$out" >&2
    rm -f "$tmp"
    return $rc
  fi

  CURL_LAST_CODE="$out"
  cat "$tmp"
  rm -f "$tmp"
  return 0
}

curl_json() {
  local url="$1"; shift || true
  local tmp body rc

  tmp="$(mktemp)"
  set +e
  curl_capture "$url" "$@" >"$tmp"
  rc=$?
  set -e

  body="$(cat "$tmp")"
  rm -f "$tmp"

  # curl-level error already printed by curl_capture
  if [[ $rc -ne 0 ]]; then
    return 1
  fi

  if [[ "${CURL_LAST_CODE}" == "0" ]]; then
    echo "[curl] ERROR calling $url" >&2
    return 1
  fi

  if ! [[ "${CURL_LAST_CODE}" =~ ^(2|3) ]]; then
    echo "[curl] HTTP ${CURL_LAST_CODE} for $url" >&2
    if [[ -n "$body" ]]; then
      echo "----- response body -----" >&2
      echo "$body" >&2
      echo "-------------------------" >&2
    fi
    return 1
  fi

  echo "$body"
  return 0
}
