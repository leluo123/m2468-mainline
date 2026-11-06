# 致谢

这个项目能走到今天，几乎每一步都是站在别人的肩膀上。下面这些人和项目，是真的帮到了我们，
不是客套。

## 最重要的三个

**[RiverKawa271828](https://github.com/RiverKawa271828)** — 我们能在魅族 21 Note 上跑起 Linux，
起点就是他的项目：

- [`nura-meizu-m2381`](https://github.com/RiverKawa271828/nura-meizu-m2381)：魅族 20（m2381）的
  Nura 内核树。我们的 DTS 骨架、regulator/pinctrl/i2c 的对齐思路、7.3.0 的 runtime PM 模型，
  都是从这棵树学来的。
- [`uefi-m2381`](https://github.com/RiverKawa271828/uefi-m2381)：同机型的 UEFI 参考实现。
- [`linux-mobile-ports`](https://github.com/RiverKawa271828/linux-mobile-ports)：移动设备移植的内核树。

如果没有这几棵树，我们要么还在从零反编译 dtbo，要么根本不知道 SM8550 上哪些节点该长什么样。

**[Project-Silicium / Mu-Silicium](https://github.com/Project-Silicium/Mu-Silicium)**
— ARM64 设备上的 Project Mu UEFI 移植。我们刷进 `boot_a`/`boot_b` 的引导镜像就是基于它构建的，
ESP 里的 `BOOTAA64.EFI` 能被 ABL 拉起，全靠这套东西。

**[meizu-sm8550-kernel/android_kernel_meizu_sm8550-devicetrees](https://github.com/meizu-sm8550-kernel/android_kernel_meizu_sm8550-devicetrees)**
— 原厂 devicetree。面板的初始化序列、DSC 参数、时序这些「只能靠实测或反推」的值，
最终的真相来源就是这里。天马 ILI7838E 这块屏能点亮，靠它。

## 内核与显示

- **[silime/linux](https://github.com/silime/linux)** — `7.3.0-dev` 分支里的
  `sm8550-meizu-20-inf.dts` 是我们 DT 的最初血统。
- **Linux 主线内核**（[kernel.org](https://kernel.org)）— 7.3.0，我们所有改动的基座。
- **[Mesa](https://gitlab.freedesktop.org/mesa/mesa)** 和 **freedreno**（Adreno 开源驱动）——
  GPU 能跑起来靠它们。
- **[wlroots](https://github.com/swaywm/wlroots)** — phoc 的底层合成器库。
- **[Phosh / phoc](https://gitlab.gnome.org/World/Phosh/phosh)** — 我们用的桌面环境。

## 基带

这一块没有现成的「一键方案」，全靠这些工具一点点问出来：

- **[linux-msm/qrtr](https://github.com/linux-msm/qrtr)** — QRTR 总线，modem 和 AP 通信的基础。
- **[linux-msm/rmtfs](https://github.com/linux-msm/rmtfs)** — 远程文件服务，EFS 读写必经之路。
- **[linux-msm/tqftpserv](https://github.com/linux-msm/tqftpserv)** — TFTP 服务，modem 启动时来拉固件。
- **[libqmi](https://gitlab.freedesktop.org/mobile-broadband/libqmi) / qmicli** — QMI 命令行工具。
  我们分析 WDS 拨号报文、DMS 上下电，都是用它。
- **[ModemManager](https://gitlab.freedesktop.org/mobile-broadband/ModemManager)** — 虽然最后我们把
  `qrtr0` 设成 unmanaged 绕开了它（它不做 Bind Mux），但前期的状态观测全靠它。

## 其他

- **[postmarketOS](https://postmarketos.org)** — rootfs 的打包思路和一堆踩坑经验参考了它。
- **[Armbian](https://www.armbian.com)** — 早期验证 UFS 启动时用过它的镜像。
- **[libqrtr-glib](https://gitlab.freedesktop.org/mobile-broadband/libqrtr-glib)** 及上面这些项目背后
  的维护者 —— 在高通平台上做 mainline，几乎所有路都是他们先蹚出来的。

## 如果哪里写错了

上面的致谢里如果有归属错误、漏掉了谁、或者链接打不开，开个 issue 告诉我，我改。
