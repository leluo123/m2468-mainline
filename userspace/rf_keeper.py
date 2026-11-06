#!/usr/bin/env python3
"""m2468 RF keeper -- keep the modem radio registered.

Why this exists
---------------
Mainline 7.3.0 on the Meizu 21 Note (m2468) can bring the modem radio up, but
the modem firmware asserts in its PLL restore path roughly every 30-45 s:

    mcpm_resrc_modem_pll.c:1213: Assertion clk_mpss_req_status == CLOCK_SUCCESS failed
    mcpm_resrc_modem_offline.c:1365: ... put offline pll back to run state failed
                                      (MSS_OFFLINE_CLK_CNTRL 0xc)

The crash is inside the modem firmware and survives every AP-side fix we tried
(CX/MX corner floors, genpd votes, IPA, AOSS collapse knobs, EFS restore).
Nothing in mainline re-arms the radio afterwards, so once it drops it stays
down forever.

What is proven to work
----------------------
The DMS power cycle re-arms the radio reliably:

    qmicli -d qrtr://0 --dms-set-operating-mode=low-power
    sleep 8
    qmicli -d qrtr://0 --dms-set-operating-mode=online

After it, the modem registers, attaches, picks 5gnr and stays up for a while
(measured: 30-45 s, sometimes ~2.5 min).  So this daemon watches the serving
system and repeats the cycle, giving "signal most of the time" instead of
"signal once".

It also restarts m2468-data after each successful cycle: data_daemon.py keeps a
single global AF_QIPCRTR socket opened at import, so after a modem crash that
socket is dead and the daemon can never recover on its own.

Escapes
-------
    touch /run/m2468-rf-keeper.pause    -> stop intervening (manual experiments)
    rm    /run/m2468-rf-keeper.pause    -> resume
"""

import os
import subprocess
import sys
import time

PAUSE = "/run/m2468-rf-keeper.pause"
LOG = "/var/log/m2468-rf-keeper.log"

POLL_S = 15          # how often we sample the serving system
DOWN_GRACE_S = 45    # radio must be down this long before we intervene
QMI_TIMEOUT = 12
LOWPOWER_SLEEP = 8   # proven value; shorter and the online transition races
SETTLE_S = 20        # after the cycle, give the modem time to register

BACKOFF_STEPS = [60, 120, 240, 300]


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(argv, timeout=QMI_TIMEOUT):
    """Run a command, return (rc, combined output). Never raises."""
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as e:
        return 127, str(e)


def serving_state():
    """Return the NAS registration state string, or None if QMI is unreachable."""
    rc, out = run(["qmicli", "-d", "qrtr://0", "--nas-get-serving-system"])
    if rc != 0 and "Registration state" not in out:
        return None
    for line in out.splitlines():
        if "Registration state" in line:
            return line.split(":", 2)[-1].strip().strip("'")
    return None


def rproc_state():
    try:
        with open("/sys/class/remoteproc/remoteproc0/state") as f:
            return f.read().strip()
    except OSError:
        return "missing"


def crash_count():
    rc, out = run(["dmesg"], timeout=15)
    if rc != 0:
        return -1
    return out.count("fatal error received")


def power_cycle():
    """The one sequence that is known to re-arm the radio."""
    log("power cycle: low-power")
    run(["qmicli", "-d", "qrtr://0", "--dms-set-operating-mode=low-power"], 20)
    time.sleep(LOWPOWER_SLEEP)
    log("power cycle: online")
    run(["qmicli", "-d", "qrtr://0", "--dms-set-operating-mode=online"], 20)


def restart_data():
    log("restarting m2468-data (its QIPCRTR socket dies with the modem)")
    run(["systemctl", "restart", "m2468-data.service"], 30)


def paused():
    return os.path.exists(PAUSE)


def main():
    log("m2468-rf-keeper starting (poll=%ds grace=%ds)" % (POLL_S, DOWN_GRACE_S))
    down_since = None
    cycles = 0
    last_cycle = 0.0

    while True:
        if paused():
            if down_since is not None:
                log("paused, backing off")
                down_since = None
            time.sleep(POLL_S)
            continue

        state = serving_state()
        rp = rproc_state()
        now = time.time()

        if state is not None and "registered" in state and "not-registered" not in state:
            if down_since is not None:
                log("radio is up (%s) after %ds down" % (state, int(now - down_since)))
            down_since = None
            cycles = 0
            time.sleep(POLL_S)
            continue

        if down_since is None:
            down_since = now
            log("radio down (state=%s rproc=%s crashes=%s), watching"
                % (state, rp, crash_count()))
            time.sleep(POLL_S)
            continue

        down_for = now - down_since
        need = DOWN_GRACE_S
        if cycles:
            need = max(DOWN_GRACE_S, BACKOFF_STEPS[min(cycles - 1, len(BACKOFF_STEPS) - 1)])
        if down_for < need:
            time.sleep(POLL_S)
            continue
        if now - last_cycle < BACKOFF_STEPS[min(cycles, len(BACKOFF_STEPS) - 1)]:
            time.sleep(POLL_S)
            continue

        if rp == "missing":
            log("remoteproc0 is gone, waiting for the modem to come back")
            time.sleep(POLL_S)
            continue

        cycles += 1
        last_cycle = now
        log("intervening (down %ds, cycle #%d)" % (int(down_for), cycles))
        power_cycle()
        time.sleep(SETTLE_S)

        state = serving_state()
        if state is not None and "registered" in state and "not-registered" not in state:
            log("recovered: %s" % state)
            down_since = None
            cycles = 0
            restart_data()
        else:
            log("still down after cycle (state=%s)" % state)
            down_since = time.time()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
