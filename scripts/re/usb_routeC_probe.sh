#!/bin/sh
# usb_routeC_probe.sh — ROUTE-C 取证：不刷机、不重启
# 判定 (a) UDC 是否在"上线-回滚"循环；(b) 谁占着 gadget 设备；(c) 控制器寄存器实况
# 用法：sh usb_routeC_probe.sh [采样次数]      默认 150 次 x 200ms = 30s
# 输出：/dev/tty0（屏幕）+ 日志（默认 /tmp/usbc.log，务必改到重启后仍保留的分区）
# 依据：Linux 7.3  udc/core.c:1760-1769,1410-1470,1803-1833  dwc3-qcom.c:600-720
#                dwc3/debugfs.c:433-445,519-556,1017-1032  dwc3/gadget.c:41-61,4974-4991
#                dev_err_probe 对 -EPROBE_DEFER 走 dev_dbg：drivers/base/core.c:5155

N=${1:-150}
OUT=${OUT:-/tmp/usbc.log}
T0=/dev/tty0
DEV=/sys/bus/platform/devices/a600000.usb
DBG=/sys/kernel/debug/usb/a600000.usb

: >"$OUT" 2>/dev/null
say() { echo "$@" >>"$OUT" 2>/dev/null; echo "$@" >"$T0" 2>/dev/null; }
nap() { usleep 200000 2>/dev/null || sleep 1; }

say "================ ROUTE-C PROBE $(date) ================"

# ---------- 0. debugfs ----------
if ! grep -q debugfs /proc/mounts; then
    mount -t debugfs none /sys/kernel/debug 2>/dev/null
fi
grep -q debugfs /proc/mounts && say "[0] debugfs OK" || say "[0] *** debugfs MISSING ***"

# ---------- 0b. 先把时钟/电源钉住：regdump 是裸读 MMIO，没有 pm_runtime 保护 ----------
echo on >"$DEV/power/control" 2>/dev/null && say "[0b] power/control=on"

# ---------- 1. 谁在 defer、为什么  ← 一句话定案 ----------
say "---- [1] devices_deferred ----"
if [ -r /sys/kernel/debug/devices_deferred ]; then
    cat /sys/kernel/debug/devices_deferred >"$T0" 2>/dev/null
    cat /sys/kernel/debug/devices_deferred >>"$OUT" 2>&1
    say "(end)"
else
    say "[1] 无 devices_deferred，退化为未绑定设备清单："
    for d in /sys/bus/platform/devices/*; do
        [ -e "$d/driver" ] || say "  UNBOUND $(basename "$d")"
    done
fi

# ---------- 2. 一次性快照 ----------
say "---- [2] snapshot ----"
say "cmdline : $(cat /proc/cmdline)"
say "bootargs: $(tr -d '\0' < /proc/device-tree/chosen/bootargs 2>/dev/null)"
say "udc     : [$(ls /sys/class/udc 2>/dev/null | tr '\n' ' ')]"
say "bus_drv : [$(ls /sys/bus/gadget/drivers 2>/dev/null | tr '\n' ' ')]"
say "bus_dev : [$(ls /sys/bus/gadget/devices 2>/dev/null | tr '\n' ' ')]"
for g in /sys/bus/gadget/devices/*; do
    [ -e "$g" ] || continue
    say "  $(basename "$g") -> drv=[$(readlink -f "$g/driver" 2>/dev/null | sed 's#.*/##')]"
done
for u in /sys/class/udc/*; do
    [ -e "$u" ] || continue
    # od -c：区分"真空串"和"读失败"，并暴露 \r 之类的脏字节
    say "  $(basename "$u") state=$(cat "$u/state" 2>/dev/null | od -An -c | tr -s ' ')"
    say "  $(basename "$u") func=[$(cat "$u/function" 2>/dev/null)] curspeed=[$(cat "$u/current_speed" 2>/dev/null)] max=[$(cat "$u/maximum_speed" 2>/dev/null)]"
done
say "pm      : ctrl=$(cat "$DEV/power/control" 2>/dev/null) runtime=$(cat "$DEV/power/runtime_status" 2>/dev/null)"
say "dbg_usb : [$(ls /sys/kernel/debug/usb 2>/dev/null | tr '\n' ' ')]"

# ---------- 3. 三方时间序列  ← 唯一能证明"抖动"的手段 ----------
say "---- [3] 时间序列 ${N}x200ms ----"
i=0
while [ "$i" -lt "$N" ]; do
    say "$(cut -d' ' -f1 /proc/uptime) udc=[$(ls /sys/class/udc 2>/dev/null | tr '\n' ' ')] g=[$(ls /sys/bus/gadget/devices 2>/dev/null | tr '\n' ' ')] dbg=[$(ls /sys/kernel/debug/usb 2>/dev/null | tr '\n' ' ')] drv=[$(for g in /sys/bus/gadget/devices/*; do [ -e "$g" ] && readlink -f "$g/driver" 2>/dev/null | sed 's#.*/##'; done | tr '\n' ' ')]"
    i=$((i + 1))
    nap
done

# ---------- 4. 寄存器实况 ----------
if [ -r "$DBG/regdump" ]; then
    say "---- [4] regdump ----"
    grep -iE 'DCFG|DCTL|DEVTEN|DSTS|DALEPENA|GCTL|GUSB2PHYCFG\(0\)|GUSB3PIPECTL\(0\)|GSNPSID' "$DBG/regdump" 2>/dev/null | while read -r l; do say "  $l"; done
    say "  判读: DCTL[31]=RunStop | DSTS[2:0]=连接速率 | DCFG[9:3]=DevAddr(非0=主机枚举过) | GCTL[13:12]=1=>device"
else
    say "[4] regdump 不存在 —— 此刻控制器 debugfs 已被摘除（=回滚中，本身就是证据）"
fi

# ---------- 5. 已知空操作，别再试（只记录，不执行） ----------
# mode: dwc3_mode_write() 首句 if (dwc->dr_mode != OTG) return count;  → peripheral 下永远 no-op
# soft_connect: 需要 udc->driver 已存在，否则 dev_err + -EOPNOTSUPP

# ---------- 6. 若是 g_serial 抢占，当场夺回（不刷机） ----------
for g in /sys/bus/gadget/devices/*; do
    [ -e "$g" ] || continue
    if [ "$(readlink -f "$g/driver" 2>/dev/null | sed 's#.*/##')" = "g_serial" ]; then
        say "[6] g_serial 占用 $(basename "$g") → unbind"
        echo "$(basename "$g")" > /sys/bus/gadget/drivers/g_serial/unbind 2>/dev/null && say "    unbind ok"
    fi
done

# ---------- 7. 控制器 liveness（安全版）：testmode 写入前会 pm_runtime_resume_and_get ----------
if [ -w "$DBG/testmode" ]; then
    echo test_j >"$DBG/testmode" 2>/dev/null
    say "[7] testmode 写入 rc=$?  (0 => 此刻 DCTL 可读、时钟在)"
    grep -iE 'DCTL|DSTS' "$DBG/regdump" 2>/dev/null | while read -r l; do say "    $l"; done
    sleep 10
    echo no_test_mode >"$DBG/testmode" 2>/dev/null
fi

say "================ DONE  日志：$OUT ================"
