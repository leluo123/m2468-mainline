# 魅族 21 Note（m2468）mainline Linux 移植

把 **魅族 21 Note（m2468，SM8550 / 骁龙 8 Gen 2）** 从 Android 跑成一台能日常用的 Linux 机器
（主线内核 7.3.0 + Debian/Nura rootfs + phosh）。

本仓库是这段时间全部的工作记录：**改过的内核代码、用户态脚本、实验证据、以及踩过的每一个坑**。
不追求好看，只求别人少走一遍我们走过的弯路。

---

## 当前状态（实话实说）

| 子系统 | 状态 | 说明 |
|---|---|---|
| 引导链 | ✅ 可用 | ABL → ESP 里的 `BOOTAA64.EFI`（EFI zboot + zstd）→ initramfs → rootfs |
| 串口 | ✅ 可用 | USB gadget 串口（`ttyGS0` / Windows 侧 COMx），115200 |
| 显示 | ✅ 可用 | 天马 ILI7838E LTPO AMOLED，1264×2780，DSC 8bpp/10bpc，**cmd mode + burst** |
| 触摸 | ✅ 可用 | QUP-GPI（不是 GENI FIFO，见 `docs/★触摸根因_QUP-GPI_20261031.md`） |
| WiFi | ✅ 可用 | 见 `docs/★WiFi已通_20261031.md` |
| 充电 | ✅ 可用 | udev 必须用 `ENV{POWER_SUPPLY_NAME}` 匹配，不能用 `ATTR{name}` |
| 基带（识别/注册） | ✅ 可用 | SIM 识别、IMEI、注册、PS attach、5G n41（中国移动） |
| 数据（4G/5G 上网） | ✅ 短暂可用 | WDS 拨号拿到真实 IP，ping/DNS/HTTP/HTTPS 全通 |
| **基带稳定性** | ❌ **未解决** | 射频起来后 30–45 秒必崩，见下 |
| 短信 / 通话 | ⏸️ 未做 | 测试卡不支持，按需求跳过 |
| 硬件视频/GPU 加速 | ❌ 未做 | 目前软件渲染（`WLR_RENDERER=pixman`） |
| 快充 | ❌ 未做 | 根因已定位（DTS 删 `usb-role-switch` 导致 UCSI EPROBE_DEFER → 900mA），修了会堵死 pmic-glink |

### 唯一的硬骨头：基带 PLL 断言

射频起来后，modem 固件在电源塌陷回 run state 时锁不住 PLL：

```
mcpm_resrc_modem_pll.c:1213: Assertion clk_mpss_req_status == CLOCK_SUCCESS failed
mcpm_resrc_modem_offline.c:1365: ... put offline pll back to run state failed
                                  (MSS_OFFLINE_CLK_CNTRL 0xc) in Up path (timeout: 100 usec)
```

**我们排除了以下假设（每条都有实测证据，见 `evidence/`）：**

| 假设 | 结论 |
|---|---|
| CX 电压角不足 | ❌ 把 CX 钉到 TURBO(384) 实测生效，断言照旧 |
| MX 电压角不足 | ❌ 钉到 NOM_L1(320) 直接起不来（MX 是 DDR/LLCC 关键域，别碰） |
| genpd 档位投票不到位 | ❌ 投票返回 0，域状态不再变化 |
| PD resume 顺序 | ❌ 强制 resume 反而触发 `ipa_hwp_init` 断言 |
| IPA / 数据流量触发 | ❌ 卸掉 ipa、停数据，照崩 |
| AOSS collapse 开关 | ❌ `prevent_cx_collapse` 等三个开关打开仍崩 |
| 系统 suspend | ❌ 已 mask 所有 sleep target，dmesg 无 suspend 记录 |
| EFS / mcfg 损坏 | ❌ 回灌备份并逐字节校验一致，SIM 正常、频段完整 |
| RF 卡文件内容 | ❌ 463/473 两种冒充行为一致 |
| 两个 modem 分区不一致 | ❌ `ver_info.txt` 完全相同 |

**剩下的差异（原厂驱动有、主线没有）**，留给后来人：

- `hyp_assign_phys()` 把 `mpss_dsm_mem` 分配给 modem（原厂 `setup_mpss_dsm_mem`）
- MSS 寄存器块 `reg = <0x4080000 0x10000>` 的 ioremap
- `qcom,signal-aop`（主线零实现）
- 互联路径 `crypto_ddr`（主线 `qcom_q6v5` 只有单条 icc path）

**⚠️ 千万不要伪造 `rf_static_464_00_00.mbn`。** 出厂固件只有 463/473，用别的冒充会让校准与硬件不匹配，
表现为 PLL 周期性崩溃。让 modem 用 `so/464_0_0.mbn` 里的内置默认校准，崩溃反而消失。

---

## 目录

```
kernel/
  dts/sm8550-meizu-21note73.dts   设备树（整机）
  panel/panel-meizu-m2468.c       面板驱动（天马 ILI7838E）
  rpmhpd-m2468.c                  rpmhpd.c 的改动版（含 CX/MX 档位下限实验代码）
userspace/
  data_daemon.py                  WDS 拨号常驻客户端（拿 IP、配 rmnet_ipa0）
  rf_keeper.py                    射频自愈守护（掉了就自动上下电）
  dms_mode.py                     DMS 工作模式读写（qmicli 读数不可信，用这个）
  bind_all.py                     NAS/VOICE/WMS/DSD/WDS 全部 Bind Subscription
  mux_matrix.py                   WDS mux 扫描
  systemd/                        对应服务单元
scripts/
  serial/                         USB 串口驱动脚本（含大脚本 base64 分步传输）
  extract/                        vendor_boot 解包（v4 头 + LZ4 legacy）
docs/                             36 篇现场记录（含每一条踩坑）
evidence/                         实验日志（正面/反面都留着）
```

## 快速上手

1. **内核**：以主线 7.3.0 为基，套用 `kernel/` 下的文件（DTS、panel 驱动、rpmhpd 改动）。
2. **构建**：`scripts/build_cxfloor.sh`（会校验 `make` 退出码和 kernel md5，不校验就可能打包旧内核）。
3. **打包 ESP**：`scripts/pack_cxfloor_esp.sh` —— **铁律：ESP 里只放 `EFI/BOOT/BOOTAA64.EFI` 和 initramfs，
   绝不放 dtb**（放 dtb 会被优先读取并覆盖运行时 DT，直接炸机）。
4. **刷机**：`scripts/flash_cxfloor.sh`。刷完记得 `fastboot --set-active=a`。
5. **串口**：`scripts/serial/send_cmd.ps1 "命令"`。

## 关于固件

固件放在**独立仓库**，避免万一有版权投诉时连累源码：
**https://github.com/leluo123/m2468-firmware**

里面是这台机器的 modem 固件（`MPSS.DE.3.0.c3-00008-KAILUA_GEN_PACK-2`）。
发布前已做精确扫描（ASCII / UTF-16LE / UTF-16BE 三种编码）：
**无 IMEI、无设备序列号、无手机号、无 MAC、无 WiFi SSID**。

**本仓库和固件仓库都不含**这些设备唯一数据：`modemst1` / `modemst2` / `fsg` / `fsc`、
QCN 备份、EFS 快照 —— 那些才是装 IMEI 和射频校准的地方，属于隐私，永不发布。

需要自己提取的话，`scripts/extract/` 下是解包工具，
基带固件在 `modem_a`/`modem_b` 分区（FAT16），RF 卡在 `mcfg/configs/mcfg_ddr/rf/`。

## 免责

刷机有变砖风险，本仓库的一切改动都在我们**自己那台机器**上验证过，不保证对你的机器成立。
自己动手前先备份 `modemst1`/`modemst2`/`fsg`/`fsc`。
