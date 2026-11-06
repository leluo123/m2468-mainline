# 魅族 21 Note（m2468）跑 Linux

把魅族 21 Note 从 Android 换成 mainline Linux（7.3.0 内核 + Debian rootfs + phosh）。
用的是 SM8550，也就是骁龙 8 Gen 2。

这个仓库是我们这段时间的全部痕迹：改过的内核代码、用户态脚本、实验证据，还有踩过的坑。
不图好看，图的是下一个做同款机型的人别再把我们踩过的坑重踩一遍。

## 现在能用到什么程度

| 子系统 | 状态 | 备注 |
|---|---|---|
| 引导 | 能用 | ABL → ESP 里的 `BOOTAA64.EFI`（EFI zboot + zstd）→ initramfs → rootfs |
| 串口 | 能用 | USB gadget 串口，115200 |
| 显示 | 能用 | 天马 ILI7838E LTPO AMOLED，1264×2780，DSC 8bpp/10bpc，cmd mode + burst |
| 触摸 | 能用 | 走 QUP-GPI。不是 GENI FIFO，别往那个方向查 |
| GPU | 能用 | Adreno 740 / freedreno，phoc 用 GLES 合成 |
| WiFi | 能用 | |
| 充电 | 能用 | |
| 基带识别与注册 | 能用 | SIM 识别、IMEI、注册、5G n41 |
| 数据上网 | 时好时坏 | WDS 拨号拿到真实 IP，ping/DNS/HTTP 都通 |
| 基带稳定性 | 没解决 | 射频起来 30 到 45 秒必崩，下面细说 |
| 短信通话 | 没做 | 测试卡不支持，按需求跳过 |
| 硬件视频解码 | 没试 | Venus 完全没碰 |
| 快充 | 没做 | 根因找到了，但修了会堵死 pmic-glink 七分钟 |

### 那个没解决的问题

射频一起来，modem 固件在电源塌陷回 run state 的时候锁不住 PLL：

```
mcpm_resrc_modem_pll.c:1213: Assertion clk_mpss_req_status == CLOCK_SUCCESS failed
mcpm_resrc_modem_offline.c:1365: ... put offline pll back to run state failed
                                  (MSS_OFFLINE_CLK_CNTRL 0xc) in Up path (timeout: 100 usec)
```

我们花了很多时间在这上面，把能想到的假设都试了一遍，一条一条被证据否掉：

| 试过的假设 | 结果 |
|---|---|
| CX 电压角不够 | 把 CX 钉到 TURBO(384)，用 pr_info 确认真的生效了，断言照旧 |
| MX 电压角不够 | 钉到 NOM_L1(320) 直接起不来，掉进 fastboot。MX 是 DDR/LLCC 的关键域，碰不得 |
| genpd 档位投票不到位 | 投票函数返回 0，域状态没有任何变化 |
| PD resume 顺序有问题 | 强制 resume 反而触发 `ipa_hwp_init` 断言，2.7 秒一循环 |
| IPA 或数据流量触发 | 卸掉 ipa、停掉数据，照样崩 |
| AOSS collapse 开关 | 三个开关全打开，照样崩 |
| 系统 suspend 导致 | 所有 sleep target 都 mask 了，dmesg 里一条 suspend 记录都没有 |
| EFS 或 mcfg 坏了 | 回灌备份并逐字节校验一致，SIM 正常、频段完整 |
| RF 卡文件内容不对 | 463 和 473 两种冒充，行为完全一样 |
| 两个 modem 分区不一致 | `ver_info.txt` 一字不差，换槽没意义 |

剩下的差异都在原厂驱动里有、主线里没有：

- `hyp_assign_phys()` 把 `mpss_dsm_mem` 分配给 modem（原厂的 `setup_mpss_dsm_mem`）
- MSS 寄存器块 `reg = <0x4080000 0x10000>` 的 ioremap
- `qcom,signal-aop`，主线里连实现都搜不到
- 互联路径 `crypto_ddr`，主线 `qcom_q6v5` 只有一条 icc path

还有一条血的教训：**永远别伪造 `rf_static_464_00_00.mbn`**。出厂固件只有 463 和 473，
拿别的冒充会让校准和硬件对不上，表现就是 PLL 周期性崩溃。让它用 `so/464_0_0.mbn` 里的
内置默认校准，崩溃反而消失。这个错我们犯了两次。

## 仓库里有什么

```
kernel/
  dts/sm8550-meizu-21note73.dts   整机设备树
  panel/panel-meizu-m2468.c       天马 ILI7838E 面板驱动
  rpmhpd-m2468.c                  rpmhpd.c 的改动版（CX/MX 档位下限的实验代码）
userspace/
  data_daemon.py                  WDS 拨号常驻客户端，拿 IP 并配 rmnet_ipa0
  rf_keeper.py                    射频自愈，掉了就自动上下电
  dms_mode.py                     DMS 工作模式读写。qmicli 读数不可信，用这个
  bind_all.py                     把 NAS/VOICE/WMS/DSD/WDS 全部 Bind Subscription
  mux_matrix.py                   WDS mux 扫描
  systemd/                        对应的服务单元
scripts/
  serial/                         USB 串口驱动脚本，含大脚本 base64 分块传输
  extract/                        vendor_boot 解包（v4 头 + LZ4 legacy）
  re/                             逆向工具：fdtparse、dtbo 解析、QCN 提取、modem 镜像分析
docs/                             36 篇现场记录
evidence/                         实验日志，失败的也留着
CREDITS.md                        这个项目站在谁的肩膀上
```

## 怎么用

1. 内核以主线 7.3.0 为基，把 `kernel/` 下的文件套进去。
2. `scripts/build_cxfloor.sh` 构建。它会检查 `make` 退出码和 kernel md5，
   不检查的话很容易打出上一次的旧内核还以为成功了。
3. `scripts/pack_cxfloor_esp.sh` 打 ESP。ESP 里只放 `EFI/BOOT/BOOTAA64.EFI` 和 initramfs，
   **不能放 dtb**，放了会被优先读取、覆盖运行时 DT，直接炸机。
4. `scripts/flash_cxfloor.sh` 刷机，刷完记得 `fastboot --set-active=a`。
5. 串口用 `scripts/serial/send_cmd.ps1 "命令"`。

想直接刷现成镜像、不想编译的，看 [Releases](https://github.com/leluo123/m2468-mainline/releases)。

## 固件

固件单独放一个仓库，免得万一有版权投诉连累源码：
**[leluo123/m2468-firmware](https://github.com/leluo123/m2468-firmware)**

里面是这台机器的 modem 固件，版本 `MPSS.DE.3.0.c3-00008-KAILUA_GEN_PACK-2`。
发布前用 ASCII、UTF-16LE、UTF-16BE 三种编码精确扫过，没有 IMEI、没有序列号、
没有手机号、没有 MAC、没有 WiFi 名。

下面这些东西永远不会进这两个仓库：`modemst1`、`modemst2`、`fsg`、`fsc`、QCN 备份、EFS 快照。
装 IMEI 和射频校准的就是它们，属于隐私。

需要自己从设备里提取的话，`scripts/extract/` 里有解包工具。基带固件在 `modem_a`/`modem_b`
分区（FAT16），RF 卡在 `mcfg/configs/mcfg_ddr/rf/`。

## 致谢

见 [CREDITS.md](CREDITS.md)。特别感谢 [RiverKawa271828](https://github.com/RiverKawa271828)
和 [Project-Silicium](https://github.com/Project-Silicium/Mu-Silicium)，没有他们我们起步不了。

## 免责

刷机有变砖风险。这些改动都在我们自己那一台机器上验证过，不保证对你的机器成立。
动手前先把 `modemst1`、`modemst2`、`fsg`、`fsc` 备份好。
