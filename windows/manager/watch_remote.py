"""Read-only 远端 snapshot. Never return credentials or raw conversation logs."""
import json
import datetime
import os
import pathlib
import re
import subprocess
import sys
import time

def connection_events(lines, cursor, observed_at):
    events = []
    pending = list(cursor.get('pending_sse', []))
    recent = [stamp for stamp in cursor.get('recent_sse', []) if observed_at - stamp <= 600]
    heartbeat = dict(cursor.get('pending_heartbeat', {}))
    recent_heartbeat = [stamp for stamp in cursor.get('recent_heartbeat', []) if observed_at - stamp <= 600]
    recent_warnings = [stamp for stamp in cursor.get('recent_warnings', []) if observed_at - stamp <= 600]
    zone = datetime.timezone(datetime.timedelta(hours=8))
    for line in lines:
        if 'Received message from webview:' in line:
            continue
        if 'CCRClient: Heartbeat failed:' in line:
            stamp = datetime.datetime.fromisoformat(line[:23]).replace(tzinfo=zone).timestamp()
            if not heartbeat:
                heartbeat = {'started': stamp, 'time': line[:23], 'failures': 0, 'alerted': False}
            heartbeat['failures'] += 1
            if heartbeat['failures'] >= 3 and not heartbeat['alerted']:
                events.append({'time': line[:23], 'category': 'ccr_heartbeat_failed'})
                heartbeat['alerted'] = True
            continue
        if 'CCRClient: Heartbeat sent' in line and heartbeat:
            stamp = datetime.datetime.fromisoformat(line[:23]).replace(tzinfo=zone).timestamp()
            duration = round(stamp - heartbeat['started'], 3)
            category = 'ccr_heartbeat_restored' if heartbeat['alerted'] or duration >= 60 else 'ccr_heartbeat_recovered'
            events.append({'time': line[:23], 'category': category, 'durationSeconds': duration})
            heartbeat = {}
            recent_heartbeat = [value for value in recent_heartbeat if stamp - value <= 600]
            recent_heartbeat.append(stamp)
            if len(recent_heartbeat) >= 3 and category == 'ccr_heartbeat_recovered':
                events.append({'time': line[:23], 'category': 'ccr_unstable'})
            continue
        if 'CCRClient: client events failed:' in line:
            # The following POST summary reports the retry count for this same failure.
            continue
        if 'CCRClient: client_events POST' in line:
            failure = re.search(r'after (\d+) earlier failure', line)
            if failure:
                attempts = int(failure.group(1)) + 1
                category = 'ccr_events_retry' if 'retrying it' in line and attempts < 3 else 'ccr_events_failed'
                events.append({'time': line[:23], 'category': category, 'failedAttempts': attempts})
            elif re.search(r'failed|no response|dropp|giving up|discard|\b[45]\d\d\b', line, re.I):
                events.append({'time': line[:23], 'category': 'ccr_events_failed'})
            continue
        if 'SSETransport: Stream read error:' in line and re.search(r'ECONNRESET|ETIMEDOUT', line):
            stamp = datetime.datetime.fromisoformat(line[:23]).replace(tzinfo=zone).timestamp()
            pending.append({'started': stamp, 'time': line[:23], 'alerted': False})
            continue
        if re.search(r'SSETransport: Connected(?:\s|$)', line) and pending:
            stamp = datetime.datetime.fromisoformat(line[:23]).replace(tzinfo=zone).timestamp()
            episode = pending.pop(0)
            duration = round(stamp - episode['started'], 3)
            category = 'sse_connection_recovered' if episode['alerted'] or duration >= 60 else 'sse_recovered'
            events.append({'time': line[:23], 'category': category, 'durationSeconds': duration})
            recent = [value for value in recent if stamp - value <= 600]
            recent.append(stamp)
            if len(recent) >= 3:
                events.append({'time': line[:23], 'category': 'sse_unstable', 'countWithinTenMinutes': len(recent)})
            continue
        category = None
        if re.search(r'claude_authenticate flow ended|OAuth refresh failed|claude_oauth_callback rejected', line, re.I):
            match = re.search(r'\b(400|401|403)\b', line)
            if match:
                category = 'auth_http_' + match.group(1)
        if category is None and re.search(r'\[error\]|\[warning\]|\[warn\]', line, re.I):
            match = re.search(r'ECONNRESET|ETIMEDOUT|ERR_PROXY_CONNECTION_FAILED|ERR_TUNNEL_CONNECTION_FAILED|Connection closed mid-response|stream disconnected', line, re.I)
            if match:
                request_failed = re.search(r'\[error\]|Connection closed mid-response|stream disconnected', line, re.I)
                category = 'connection_interrupted' if request_failed else 'network_warning'
                if category == 'network_warning':
                    stamp = datetime.datetime.fromisoformat(line[:23]).replace(tzinfo=zone).timestamp()
                    recent_warnings = [value for value in recent_warnings if stamp - value <= 600]
                    recent_warnings.append(stamp)
                    if len(recent_warnings) >= 3:
                        events.append({'time': line[:23], 'category': 'network_unstable'})
        if category:
            events.append({'time': line[:23], 'category': category})
    for episode in pending:
        if not episode['alerted'] and observed_at - episode['started'] >= 60:
            events.append({'time': episode['time'], 'category': 'sse_connection_stalled'})
            episode['alerted'] = True
    if heartbeat and not heartbeat['alerted'] and observed_at - heartbeat['started'] >= 60:
        events.append({'time': heartbeat['time'], 'category': 'ccr_heartbeat_failed'})
        heartbeat['alerted'] = True
    return events, {'pending_sse': pending, 'recent_sse': recent,
                    'pending_heartbeat': heartbeat, 'recent_heartbeat': recent_heartbeat,
                    'recent_warnings': recent_warnings}


def snapshot(cursor):
    home = pathlib.Path.home()
    status = pathlib.Path('/run/user') / str(os.getuid()) / 'claude-ip-gate/status'
    gate = dict(line.split('=', 1) for line in status.read_text().splitlines() if '=' in line) if status.exists() else {}
    environment = os.environ.copy()
    environment.update(HTTP_PROXY='http://127.0.0.1:17898', HTTPS_PROXY='http://127.0.0.1:17898', NO_PROXY='localhost,127.0.0.1,::1')
    auth_result = subprocess.run([str(home / '.local/bin/claude'), 'auth', 'status'],
                                env=environment, capture_output=True, text=True, timeout=15)
    auth = json.loads(auth_result.stdout)
    logs = list((home / '.vscode-server/data/logs').glob('*/exthost*/Anthropic.claude-code/Claude VSCode.log'))
    events = []
    next_cursor = {}
    observed_at = time.time()
    if logs:
        log = max(logs, key=lambda item: item.stat().st_mtime)
        size = log.stat().st_size
        same_log = cursor.get('path') == str(log)
        offset = cursor.get('offset', size) if same_log else size
        if offset > size:
            offset = 0
            same_log = False
        with log.open('rb') as stream:
            stream.seek(max(offset, size - 131072))
            lines = stream.read().decode(errors='replace').splitlines()
        events, stream_state = connection_events(lines, cursor if same_log else {}, observed_at)
        next_cursor = {'path': str(log), 'offset': size, **stream_state}
    return {
        'observedAt': observed_at,
        'gate': {key: gate.get(key) for key in ['status', 'reason', 'ipify_ip', 'cloudflare_ip', 'cloudflare_country', 'checked_epoch']},
        'auth': {'loggedIn': auth.get('loggedIn'), 'authMethod': auth.get('authMethod')},
        'events': events[-20:],
        'cursor': next_cursor,
    }


if __name__ == '__main__':
    print(json.dumps(snapshot(json.load(sys.stdin))))
