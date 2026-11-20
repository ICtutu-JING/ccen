"""Quiet Windows monitor; status reads only, with no automatic repairs."""
import ctypes
import ctypes.wintypes
import datetime
import json
import os
import pathlib
import shlex
import subprocess
import sys
import time

DATA = pathlib.Path(os.environ['APPDATA']) / 'ClaudeConnectionManager/watch'
GUARD_STATUS = DATA.parent / 'guard/status.json'
SSH = pathlib.Path(os.environ['WINDIR']) / 'System32/OpenSSH/ssh.exe'
from deployment import EXPECTED_IP, EXPECTED_COUNTRY, HOST
LOCAL_INTERVAL = 30
REMOTE_INTERVAL = 120
HIDDEN = subprocess.CREATE_NO_WINDOW


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(file, value):
    file.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def event(kind, component, condition, message):
    with (DATA / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'at': now(), 'kind': kind, 'component': component,
                                 'condition': condition, 'message': message}, ensure_ascii=False) + '\n')


def notify(message, recovery=False):
    quoted = message.replace("'", "''").replace('\n', ' ')
    icon = 'Information' if recovery else 'Warning'
    tip_icon = 'Info' if recovery else 'Warning'
    command = (
        "$ErrorActionPreference='Stop';"
        'Add-Type -AssemblyName System.Windows.Forms;'
        'Add-Type -AssemblyName System.Drawing;'
        '$claudeNotice=New-Object System.Windows.Forms.NotifyIcon;'
        f'$claudeNotice.Icon=[System.Drawing.SystemIcons]::{icon};'
        "$claudeNotice.Text='Claude 连接监控';$claudeNotice.Visible=$true;"
        f"$claudeNotice.ShowBalloonTip(8000,'Claude 连接监控','{quoted}',[System.Windows.Forms.ToolTipIcon]::{tip_icon});"
        'Start-Sleep -Seconds 10;$claudeNotice.Dispose();'
    )
    return subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=HIDDEN)


def browser_snapshot():
    try:
        state = json.loads(GUARD_STATUS.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError):
        return 'status_unavailable', '本机守卫状态暂时无法读取', False, {}
    observed = state.get('observed') or {}
    details = {key: state.get(key) for key in ['pid', 'allowed', 'reason', 'checkedAt', 'activeTunnels']}
    details['observed'] = {key: observed.get(key) for key in ['ip', 'loc', 'colo']}
    if observed.get('ip') and observed['ip'] != EXPECTED_IP or observed.get('loc') and observed['loc'] != EXPECTED_COUNTRY:
        return 'exit_mismatch', '本机守卫报告出口 IP 或国家不符，请暂停使用并检查', True, details
    if not state.get('allowed'):
        return 'blocked', '本机浏览器守卫已停止放行', True, details
    checked = state.get('checkedAt')
    age = time.time() - datetime.datetime.fromisoformat(checked.replace('Z', '+00:00')).timestamp() if checked else float('inf')
    if age > 45 or state.get('reason') != 'verified':
        return 'verification_degraded', '本机出口探测持续异常，现有连接可能仍在转发', False, details
    return 'healthy', '本机浏览器守卫已恢复正常', False, details


def remote_snapshot(cursor):
    source = pathlib.Path(__file__).with_name('watch_remote.py').read_text(encoding='utf-8')
    try:
        result = subprocess.run([str(SSH), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                                 '-o', 'ConnectionAttempts=1', HOST, 'python3 -c ' + shlex.quote(source)],
                                input=json.dumps(cursor), capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=28, creationflags=HIDDEN)
    except subprocess.TimeoutExpired:
        return None, 'ssh_timeout'
    if result.returncode:
        return None, 'remote_read_failed'
    return json.loads(result.stdout), None


def remote_condition(snapshot):
    gate = snapshot['gate']
    ip = gate.get('ipify_ip')
    country = gate.get('cloudflare_country')
    if ip and ip != EXPECTED_IP or gate.get('cloudflare_ip') and gate['cloudflare_ip'] != EXPECTED_IP or country and country != EXPECTED_COUNTRY:
        return 'exit_mismatch', '远端 守卫报告出口 IP 或国家不符，请暂停使用并检查', True
    if gate.get('status') == 'degraded':
        return 'new_connections_paused', '远端 出口探测未通过：新连接暂停，已建立连接保留', True
    if gate.get('status') != 'allowed':
        return 'blocked', '远端 远端守卫已停止放行', True
    age = snapshot['observedAt'] - float(gate.get('checked_epoch') or 0)
    if age > 120 or gate.get('reason') != 'all checks passed':
        return 'verification_degraded', '远端 出口核验持续异常', False
    return 'healthy', '远端 远端守卫已恢复正常', False


def plugin_notice(item):
    category = item['category']
    if category == 'network_warning':
        return '远端 插件记录到单次网络警告，尚未判定会话中断', False, False
    if category == 'network_unstable':
        return '远端 插件在 10 分钟内记录到至少 3 次网络警告', True, False
    if category == 'ccr_events_retry':
        return '远端 后台控制事件请求未获响应，客户端已安排重试', False, False
    if category == 'ccr_heartbeat_recovered':
        return f"远端 后台心跳失败后 {item['durationSeconds']:.1f} 秒再次发送成功", False, False
    if category == 'ccr_heartbeat_restored':
        return '远端 后台控制通道的心跳已恢复', True, True
    if category == 'ccr_heartbeat_failed':
        return '远端 后台控制通道心跳持续失败，请检查连接', True, False
    if category == 'ccr_events_failed':
        return '远端 后台控制事件提交连续失败或已放弃重试', True, False
    if category == 'ccr_unstable':
        return '远端 后台心跳在 10 分钟内反复失败至少 3 次', True, False
    if category == 'sse_recovered':
        return f"远端 事件连接已在 {item['durationSeconds']:.1f} 秒后自动恢复", False, False
    if category == 'sse_connection_recovered':
        return f"远端 事件连接已恢复，曾中断 {item['durationSeconds']:.0f} 秒", True, True
    if category == 'sse_connection_stalled':
        return '远端 事件连接中断后超过 60 秒未恢复', True, False
    if category == 'sse_unstable':
        return '远端 事件连接在 10 分钟内反复中断至少 3 次', True, False
    message = '远端 插件出现新的认证请求错误' if category.startswith('auth_') else '远端 插件记录到连接中断，请检查对应请求'
    return message, True, False


def monitor(once=False):
    trackers = {}
    cursor = {}
    last_remote = float('-inf')
    cooldown = {}
    latest_remote = None
    last_remote_at = None

    def observe(component, condition, message, immediate=False):
        previous = trackers.get(component, {'condition': None, 'count': 0, 'alerted': None})
        count = previous['count'] + 1 if previous['condition'] == condition else 1
        alerted = previous['alerted']
        if condition != previous['condition'] and (previous['condition'] is not None or condition != 'healthy'):
            event('state_change', component, condition, message)
        if condition == 'healthy' and alerted:
            if not once:
                notify(message, recovery=True)
            event('recovery', component, condition, message)
            alerted = None
        elif condition != 'healthy' and (immediate or count >= (3 if component == 'browser' else 2)) and alerted != condition:
            if not once:
                notify(message)
            event('alert', component, condition, message)
            alerted = condition
        trackers[component] = {'condition': condition, 'count': count, 'alerted': alerted}

    event('started', 'monitor', 'running', '只读监控已启动')
    while not (DATA / 'pause').exists():
        condition, message, immediate, browser = browser_snapshot()
        observe('browser', condition, message, immediate)
        if time.monotonic() - last_remote >= REMOTE_INTERVAL:
            latest_remote, error = remote_snapshot(cursor)
            last_remote = time.monotonic()
            last_remote_at = now()
            if error:
                observe('remote_access', error, '监控暂时无法读取 远端；这不等于账号被封')
            else:
                observe('remote_access', 'healthy', '远端 监控读取已恢复')
                condition, message, immediate = remote_condition(latest_remote)
                observe('remote_gate', condition, message, immediate)
                if latest_remote['auth']['loggedIn'] is None:
                    raise RuntimeError('Claude auth status omitted loggedIn')
                signed_in = latest_remote['auth']['loggedIn']
                observe('authentication', 'healthy' if signed_in else 'signed_out',
                        '远端 Claude 登录状态已恢复' if signed_in else '远端 Claude 当前未登录，需检查授权')
                for item in latest_remote['events']:
                    category = item['category']
                    message, should_notify, recovery = plugin_notice(item)
                    if not should_notify:
                        kind = ('transient_recovered' if category in ['sse_recovered', 'ccr_heartbeat_recovered']
                                else 'retry_scheduled' if category == 'ccr_events_retry' else 'network_warning')
                        event(kind, 'vscode', category, message)
                        continue
                    if time.monotonic() - cooldown.get(category, float('-inf')) >= 900:
                        event('plugin_recovery' if recovery else 'plugin_error', 'vscode', category, message)
                        if not once:
                            notify(message, recovery=recovery)
                        cooldown[category] = time.monotonic()
                cursor = latest_remote.pop('cursor')
        state = {'updatedAt': now(), 'pid': os.getpid(), 'running': True, 'readOnly': True,
                 'localIntervalSeconds': LOCAL_INTERVAL, 'remoteIntervalSeconds': REMOTE_INTERVAL,
                 'browser': browser, 'remoteCheckedAt': last_remote_at, 'remote': latest_remote,
                 'conditions': trackers}
        write_json(DATA / 'status.json', state)
        if once:
            print(json.dumps(state, ensure_ascii=False))
            return
        time.sleep(LOCAL_INTERVAL)
    event('stopped', 'monitor', 'paused', '监控已暂停')
    write_json(DATA / 'status.json', {'updatedAt': now(), 'running': False, 'paused': True})


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    if '--stop' in sys.argv:
        (DATA / 'pause').touch()
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.wintypes.HANDLE
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    handle = kernel.CreateMutexW(None, False, 'Local\\ClaudeConnectionWatch')
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        return
    if '--start' in sys.argv:
        (DATA / 'pause').unlink(missing_ok=True)
    try:
        monitor(once='--once' in sys.argv)
    finally:
        kernel.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    DATA.mkdir(parents=True, exist_ok=True)
    if sys.executable.lower().endswith('pythonw.exe'):
        sys.stderr = (DATA / 'monitor.log').open('a', encoding='utf-8', buffering=1)
    main()
