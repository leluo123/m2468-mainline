# 魅族 21 Note (m2468 / SM8550) mainline rootfs 部署方案

**日期**：2026-10-29
**前提**：Mu-UEFI 启动链 + 自编 Linux 7.3.0 已跑通，USB CDC-ACM console = COM16，UFS 全可用，sda23 = userdata ≈ 387.8 GiB（4096 字节逻辑块）
**目标**：rootfs 从内存盘搬到 sda23，进真实用户空间（systemd + 可编译）

---

## 0. 一分钟结论

| 项 | 结论 |
|---|---|
| 文件系统 | **ext4**（不是 f2fs —— 内核根本没编 f2fs，见 §1） |
| 在哪 mkfs | **PC（WSL）上用 `mke2fs -d` 直接烤出镜像**，设备上不格式化 |
| rootfs 发行版 | **Debian 13 (trixie) arm64，mmdebstrap 制作，预装 build-essential** |
| 怎么写入 UFS | **`fastboot flash userdata`（sparse 镜像）**；备选：gadget mass_storage + PC 裸写 |
| cmdline | 必须改 **`.config` 里的 CONFIG_CMDLINE 再重编内核**（`CONFIG_CMDLINE_FORCE=y`，bootloader 传参被忽略） |
| initramfs | **保留**（1 MB 不变），改成「建 gadget → switch_root」，起不来就留 shell |
| 最大风险 | 设备**没有网络**，`apt install` 在 WiFi 修好前不可能真正可用；Android 侧 userdata 会被毁，回 Android 必须 `fastboot -w` |

---

## 1. 现状核对（以下都是在本机实测出来的，不是推测）

从 `/home/shrp/lmp73/.config` 读出来的硬事实：

| 配置 | 值 | 意义 |
|---|---|---|
| `CONFIG_EXT4_FS` | `=y` | ext4 可用 ✅ |
| `CONFIG_F2FS_FS` | **`# ... is not set`** | **f2fs 完全没编**，f2fs 方案当场判死 ❌ |
| `CONFIG_CMDLINE_FORCE` | `=y` | **bootloader 给的 cmdline 被内核丢弃**，只能用编译进内核的那串 ⚠️ |
| `CONFIG_BLK_DEV_INITRD` | `=y` | initramfs 机制在 ✅ |
| `CONFIG_DEVTMPFS` / `_MOUNT` | `=y` | /dev 自动，ttyGS0 节点会自动重建 ✅ |
| `CONFIG_USB_CONFIGFS` / `_ACM` / `_MASS_STORAGE` | `=y` / `=y` / `=y` | composite gadget（acm + 大容量存储）能做 ✅ |
| `CONFIG_USB_F_MASS_STORAGE` | `=y` | gadget 里加 LUN 可行 ✅ |
| `CONFIG_USB_MASS_STORAGE` | `=m` | 老式 `g_mass_storage` 是模块 → **没 .ko，不可用**，必须用 configfs 新接口 |
| `CONFIG_MODULES` | `=y` | 但 initramfs 里没有任何 .ko，所以 `=m` 一律等于没有 |
| `CONFIG_CRYPTO_XTS` | `=m` | ⇒ 没有 fscrypt/XTS，**分区加密不可用**（不需要） |
| `CONFIG_OVERLAY_FS` | `=m` | ⇒ 不能做 overlay root（不需要） |
| `CONFIG_CGROUPS` / 各 namespace / `SECCOMP` / `AIO` / `INOTIFY` / `FANOTIFY` / `TMPFS` / `TMPFS_XATTR` / `EXT4_FS_POSIX_ACL` / `EXT4_FS_SECURITY` | 全是 `=y` | **systemd 需要的全齐** ✅ |
| `CONFIG_DEFAULT_SECURITY_DAC`，`CONFIG_LSM="landlock,..."` | — | 没 SELinux，不会卡标签 ✅ |

UFS（dmesg 实测）：`[sda] 124010496 4096-byte logical blocks (508 GB/473 GiB)`，`Preferred minimum I/O size 524288 bytes`。

initramfs 实测：`/home/shrp/initramfs.cpio.gz` = **1,007,180 字节**，31 个条目，busybox 1,914,704 字节。
用 `strings` 查这个 busybox **确实带**这些 applet（init 里 `/bin/busybox --install -s /bin` 会全部建链接）：
`switch_root` ✅ `chroot` ✅ `mke2fs`(busybox 版，只能 ext2/ext3) ✅ `fdisk` ✅ `losetup` ✅ `base64` ✅ `gzip/gunzip` ✅ `xzcat` ✅ `getty` ✅ `mdev` ✅ `reboot/poweroff` ✅
**不带**：`tar`、`blkid`、`mkfs.ext4`、`e2fsck`、`insmod` 之外的内核工具（`insmod` 有但没 .ko 可用）。

> 结论：**switch_root 现成可用**，不需要重编 busybox。这是本方案能省一半工作量的关键点。

PC 侧工具实测：`C:\platform-tools\` 里有 `fastboot.exe 36.0.0` 和 **`mke2fs.exe`（1.46.6，带 `-d root-directory`）**、`make_f2fs.exe`。WSL 里 `mke2fs 1.47.2`、`aarch64-linux-gnu-gcc 15.2.0`、loop 挂载、`sudo` 免密、`/home` 812 GB 空闲、`C:` 103 GB 空闲 —— 都正常。

---

## 2. 文件系统选择：ext4

**选 ext4，理由不是偏好，是被内核决定的：**

1. **`# CONFIG_F2FS_FS is not set`** —— 想用 f2fs 就必须重编内核把 f2fs 打开（还要连带 `CONFIG_CRYPTO_XTS` 从 `=m` 改 `=y` 才有加密，而 `CONFIG_F2FS_FS_SECURITY` 之类也要一起开）。为省事不值得，ext4 一行配置都不用改。
2. Android 原来用 f2fs + `dm-default-key`/metadata 加密，但那些密钥在 **metadata 分区**，不在 userdata 里；我们直接把 userdata 整个重做，不存在「f2fs 残留元数据污染」问题。反过来说，**千万不要动 metadata / super 等分区**，否则 Android 侧也救不回来。
3. ext4 在 4K 逻辑块设备上只要 **block size = 4096** 就没问题；而且它支持**在线扩容到 388 GiB**（`resize2fs`），f2fs 还得额外工具。
4. 无电池/可能硬复位 → ext4 的 journal 比 busybox 能造的 ext2 强得多（本方案最终镜像就是带 journal 的纯 ext4）。

### 512 vs 4096 扇区这个坑，落到 mkfs 上是什么

- 设备逻辑块是 **4096**。ext4 挂载时 `set_blocksize()` 的块大小不能小于设备逻辑块大小 —— 所以 **`-b 1024` / `-b 2048` 的 ext4 在 sda23 上挂载会失败**（具体报错文本不确定，需实测；表现是 mount 直接失败而不是只读）。
- 因此：**`-b 4096` 是硬要求**，镜像的 block size 必须等于 4096。
- 超级块里没有独立「扇区大小」字段需要调，4096 块大小即可；`mke2fs` 也不会去探测 PC 侧文件的物理扇区（文件没有物理扇区），所以 PC 上做出来的 4096 块 fs 拿到 4K 设备上完全合法。
- 注意这和 **ESP(sda22) 那个 `fs/fat/inode.c:1659` -EIO 坑是两件事**：那个是 FAT 驱动把 512 字节扇区 FAT32 挂到 4096 逻辑块设备上才炸；ext4 不走那条路径。

### 具体 mkfs 命令（PC 侧，WSL，实测跑通过）

```bash
# 1) 目录版（推荐，ownership/权限/符号链接最保真）
sudo mke2fs -t ext4 -b 4096 -m 1 -L M2468ROOT \
  -U 5c1b7f10-2b7a-4d34-9d0e-1f2a3b4c5d6e \
  -E lazy_itable_init=1,root_owner=0:0 \
  -d /home/shrp/m2468root \
  -F /home/shrp/m2468-ext4.img 8G
```

```bash
# 2) tar 版（mke2fs -d 也吃 tar，但只吃未压缩 .tar；实测 .tar.gz 会报
#    "populate_fs2: 没有那个文件或目录 ... 填充文件系统时" 失败）
sudo tar -C /home/shrp/m2468root -cf /home/shrp/m2468root.tar .   # 注意结尾的 .
truncate -s 8G /home/shrp/m2468-ext4.img
sudo mke2fs -t ext4 -b 4096 -m 1 -L M2468ROOT \
  -U 5c1b7f10-2b7a-4d34-9d0e-1f2a3b4c5d6e \
  -d /home/shrp/m2468root.tar -F /home/shrp/m2468-ext4.img
```

实测这套参数产生的特性集（`dumpe2fs -h`）：
`has_journal ext_attr resize_inode dir_index orphan_file filetype extent 64bit flex_bg metadata_csum_seed sparse_super large_file huge_file dir_nlink extra_isize metadata_csum`，`Block size: 4096`，`Inode size: 256`。
`orphan_file` 要内核 ≥5.15、`metadata_csum_seed` 要 ≥5.x —— 7.3.0 全支持，没问题。
`64bit` + `resize_inode` ⇒ 以后能 `resize2fs` 在线扩到 387.8 GiB。

**尺寸策略**：先做 **8 GiB** 镜像（够 Debian+工具链+后续装东西），首启稳定后在设备上扩到整分区：

```bash
e2fsck -f /dev/sda23 && resize2fs /dev/sda23     # 在设备上跑，388GiB 大概几分钟
```
（8 GiB 而不是 388 GiB 的原因：fastboot/USB 写入量 = 镜像大小，先小后扩能省 40 倍传输时间。）

---

## 3. 在哪格式化：三条路的取舍

| 方案 | 可行性 | 判定 |
|---|---|---|
| a) 把 mkfs 编进 initramfs | busybox 自带 `mke2fs` 只能造 ext2/ext3（无 extent、无 64bit、无 metadata_csum）；想造真 ext4 要交叉编译 e2fsprogs 静态版塞进 initramfs（约 +1.5 MB，未实测） | **只当 fallback** |
| b) PC 通过 USB 把设备当盘格 | 设备当 U 盘时 Windows 只能整盘裸写，Windows 没有 ext4 驱动，**不能"在上面格 ext4"**；WSL2 要 `usbipd-win`（本机**没装**） | 不划算 |
| c) cmdline 自动格式化 | 内核没有这种功能（`rootfstype=` 只选类型不造 fs） | 不存在这条路 |
| **d) PC 侧 `mke2fs -d` 直接烤出成品镜像** | WSL 里 mke2fs 1.47.2 + `-d` + loop 校验，**已实测成功**；一次搞定「格式化 + 灌 rootfs + 定 UUID + 定块大小 4096」 | ✅ **推荐** |

方案 d 的额外好处：镜像在 PC 上是文件，可以先 `e2fsck -fn`、`mount -o loop` 检查 `/sbin/init` 在不在、`/etc/fstab` 对不对，**上机前就能验证**，不用拿设备当盲盒。

设备侧保留的 fallback（万一 fastboot 和 gadget 全挂）：在 initramfs 的 busybox shell 里

```sh
mke2fs -b 4096 -t ext3 -L M2468ROOT /dev/sda23     # busybox 版，只有 ext3 能力
```
之后启动进系统再原地升级成 ext4（`tune2fs -O extents,uninit_bg,dir_index,metadata_csum /dev/sda23 && e2fsck -fD /dev/sda23`）。
这条路**没有 64bit/没有 metadata_csum、还可能很慢**，只当救急，不作为主方案。

---

## 4. rootfs 来源（下载地址都是刚用 `curl -I` 验过的，大小是 Content-Length 实测值）

| # | 来源 | URL | 压缩包大小 | 包管理 | 适合度 |
|---|---|---|---|---|---|
| 1 | **Debian 13 trixie arm64（mmdebstrap 现场制作）** | `https://mirrors.tuna.tsinghua.edu.cn/debian`（Release 页 200 OK）；备份 `https://mirrors.aliyun.com/debian` | 下载量约 200–400 MB（估算，取决于 include 列表） | apt/dpkg | ⭐**首选**：能一次性把 `build-essential`、`git`、`python3`、`e2fsprogs` 全烤进去；glibc；包最全；Debian 的 `foreign`/`second-stage` 机制对「离线半成品」也友好 |
| 2 | Ubuntu base 24.04.5 arm64 | `https://mirrors.tuna.tsinghua.edu.cn/ubuntu-cdimage/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.5-base-arm64.tar.gz`（阿里云同路径也有） | **29,936,675 B ≈ 28.5 MiB** | apt/dpkg | 次选：最小最快，但没有 qemu 就很难往里加 gcc，得靠 debootstrap 式二次处理 |
| 3 | Alpine 3.22.7 aarch64 minirootfs | `https://mirrors.tuna.tsinghua.edu.cn/alpine/v3.22/releases/aarch64/alpine-minirootfs-3.22.7-aarch64.tar.gz` | **3,971,679 B ≈ 3.8 MiB** | apk | 只当**串口救砖**用（3.8 MB 走 115200 大约 8 分钟能传完）；musl + 工具链坑多，不适合长期当开发机 |
| 4 | Debian arm64 netinst ISO（只想救急装系统时） | `https://mirrors.tuna.tsinghua.edu.cn/debian-cd/current/arm64/iso-cd/debian-13.7.0-arm64-netinst.iso` | 数百 MB | apt | 设备没显示没键鼠，装不了安装器，**不用** |

> 境外网络基本不通（只有 api.github.com 直连）。所以**不要**用 `cdimage.ubuntu.com`、`deb.debian.org`、`images.linuxcontainers.org`、GitHub release/raw（必要时加 `https://gh-proxy.com/` 前缀）。上面 1–3 全是清华/阿里国内镜像，已实测 200。

### 制作命令（WSL，root）

```bash
sudo apt-get install -y mmdebstrap qemu-user-binfmt binfmt-support android-sdk-libsparse-utils
# 上面四个包在 aliyun 源里都有候选版本（已 apt-cache 验过），android-sdk-libsparse-utils 提供 img2simg

sudo mmdebstrap \
  --arch=arm64 --variant=important \
  --components="main contrib non-free non-free-firmware" \
  --include="systemd,systemd-sysv,udev,dbus,kmod,util-linux,e2fsprogs,iproute2,ca-certificates,\
curl,wget,sudo,locales,tzdata,fake-hwclock,less,nano,vim-tiny,rsync,htop,strace,file,\
unzip,zip,xz-utils,zstd,build-essential,git,python3,pkg-config,libssl-dev,bc,flex,bison,\
libncurses-dev,device-tree-compiler,openssh-server,parted" \
  --customize-hook='/home/shrp/m2468-hook.sh "$1"' \
  trixie /home/shrp/m2468root \
  https://mirrors.tuna.tsinghua.edu.cn/debian
```

**注意**：`qemu-user-static` 在 aliyun 的 resolute 源里**没有候选**（只有 `qemu-user` / `qemu-user-binfmt`），`mmdebstrap` 用 `qemu-user-binfmt` 注册 aarch64 binfmt 就行。WSL2 的 `binfmt_misc` 一般可用，**但这条需要实测**（`ls /proc/sys/fs/binfmt_misc/` 里有 `qemu-aarch64` 才算注册成功）。如果 binfmt 起不来，退路是 `debootstrap --foreign` + 首次启动用 `init=/bin/bash` 进半成品 rootfs 在**设备上原生跑** `/debootstrap/debootstrap --second-stage`（arm64 原生，不用模拟）。

**耗时预期**：qemu 模拟下装 250+ 个包，**预计 20–90 分钟（不确定，看 CPU）**。想快就砍 `--include`（先不要 gcc，等设备起来再补）。

### 离线装包的真相（必须说清）

`apt install` 需要网络，而**这台设备现在没有网络**（PCIe/WiFi 还没修）。所以在 WiFi 修好之前：

- `apt update` 一定失败（而且**日期是 1970 时 HTTPS 证书直接 not yet valid**，所以装 `fake-hwclock` 并 `date -s` 改对时间是第一步）。
- 能干的是**离线包仓库**：PC 上把 .deb 攒齐 → 放进镜像的 `/opt/debs/` → 设备上
  ```bash
  cd /opt/debs && dpkg-scanpackages . /dev/null > Packages && gzip -kf Packages
  echo "deb [trusted=yes] file:/opt/debs ./" > /etc/apt/sources.list.d/local.list
  apt-get -o Acquire::Check-Valid-Until=false update && apt-get install -y <包名>
  ```
- 攒 deb 的最好办法：用同一个 mmdebstrap 环境 `apt-get install --download-only -o Dir::Cache::archives=... <包名>`（这套环境本身就是 arm64，依赖解析 100% 对得上）。
- **所以「能 apt/dnf 装包」这个目标，在第一版里请理解成「能 dpkg/apt 从本地仓库装包」**，在线 apt 要等 WiFi。

---

## 5. 怎么把 rootfs 写进 UFS（4 条路的速度账）

| 方案 | 传输量 | 速度 | 判定 |
|---|---|---|---|
| a) 塞进 initramfs | Debian 1.5–2.5 GB → gz 后 initramfs 会到 GB 级，内核 Image 47 MB + 这个；而 ESP 只有 256 MiB，Mu 加载也扛不住 | — | ❌ 不可行 |
| b) 串口 xmodem/base64 | 115200 bps ≈ 11.5 KB/s，base64 膨胀 4/3 → **净 ≈8.6 KB/s**。8 GiB = **约 11 天**；Alpine 3.8 MB ≈ 8 分钟 | 极慢 | ⚠️ 只当最后救急（且 busybox 没有 `rx`，要手搓 base64 分块） |
| c) gadget mass_storage 指向 /dev/sda23 → PC 裸写镜像 | 8 GiB，USB3(dwc3)+UFS，估计 100–300 MB/s → **30 秒–2 分钟** | 快 | ✅ 备选/主力更新通道（需要 Windows 裸写盘，见下） |
| **d) `fastboot flash userdata <sparse.img>`** | 8 GiB（稀疏后实际更少），估计 50–150 MB/s → **1–3 分钟** | 快 | ✅✅ **首选**：工具链现成、流程你已经在用（rawdump 就是这么刷的）、不依赖设备端任何东西 |
| e) 放 ESP (sda22) | 256 MiB 放不下；且 Linux 侧 vfat 挂载因 512 扇区 FAT32 / 4096 逻辑块 bug **直接 -EIO**，读不了 | — | ❌ 判死 |

### 推荐路径 d：fastboot 刷 userdata

```powershell
# PC，管理员 PowerShell；手机先进 fastboot（Android fastboot 模式）
fastboot devices
fastboot getvar max-download-size          # 记下来，常见 256MiB / 1GiB

# 8GiB 裸镜像必须转稀疏，否则大概率 "data too large"
wsl -d Ubuntu -- bash -lc "img2simg /home/shrp/m2468-ext4.img /home/shrp/m2468-ext4.simg 268435456"
# 精简后的 image 只有几十 MB（稀疏），拷到 C: 给 fastboot 用（fastboot 认不了 \\wsl$ 路径）
wsl -d Ubuntu -- bash -lc "cp /home/shrp/m2468-ext4.simg /mnt/c/Users/Administrator/Desktop/meizu21note_Mu/"

fastboot flash userdata C:\Users\Administrator\Desktop\meizu21note_Mu\m2468-ext4.simg
fastboot reboot
```
（`img2simg` 来自 `android-sdk-libsparse-utils`，aliyun 源有。**"ABL 是否允许 flash userdata" 这条未实测，需要你验证**；如果报 permission/unknown partition，直接走方案 c。）

### 备选路径 c：gadget 把 sda23 当 U 盘给 PC，PC 裸写

关键点：**acm console 和 mass_storage 必须做成同一个 composite gadget**，否则断开 console 那 2 秒你就是瞎的。设备端（COM16，busybox shell）：

```sh
G=/sys/kernel/config/usb_gadget/g1
UDC=$(ls /sys/class/udc | head -1)
echo "" > $G/UDC                      # 先解绑（console 掉 1-2 秒）
mkdir -p $G/functions/mass_storage.0
echo /dev/sda23 > $G/functions/mass_storage.0/lun.0/file
echo 0 > $G/functions/mass_storage.0/lun.0/removable
echo 0 > $G/functions/mass_storage.0/lun.0/nofua
ln -sf $G/functions/mass_storage.0 $G/configs/c.1/mass_storage.0
echo $UDC > $G/UDC                    # 重新绑定：COM16 回来 + Windows 多出一个 388GiB 磁盘
```
PC 侧（管理员 PowerShell，先 `Get-Disk` 确认是哪个 `PhysicalDriveN`，**认错盘会毁 PC**）：

```powershell
$src="C:\Users\Administrator\Desktop\meizu21note_Mu\m2468-ext4.img"
$dst="\\.\PhysicalDrive3"
$fs=[IO.File]::Open($dst,'Open','Write','None'); $in=[IO.File]::OpenRead($src)
$buf=New-Object byte[] 4194304
while(($n=$in.Read($buf,0,$buf.Length)) -gt 0){ $fs.Write($buf,0,$n) }
$fs.Flush(); $in.Close(); $fs.Close()
```
写完在设备上 `echo "" > $G/UDC` 解绑，再 `mount -t ext4 /dev/sda23 /mnt` 验一下。整个过程 console 会闪断，但 gadget 一直在。

---

## 6. 内核 cmdline 改动（这里有硬坑）

**`CONFIG_CMDLINE_FORCE=y`** ⇒ 内核只用编译进去的那串字符串，bootloader/DTB 传的 bootargs 被**整条丢弃**。所以：
- 不需要碰 Mu 的 DTB —— 但**必须重编内核**（改 `.config` → `make Image` → 重做 boot_b，dtb 还是烤在 Mu FV 里那套流程不变）。
- 反过来这也是好消息：**回滚 = 刷回旧 boot_b**，不依赖设备状态。

改这一行（保留全部原有参数，尾部只加 root 相关）：

```
CONFIG_CMDLINE="acpi=off earlycon=efifb keep_bootcon console=tty0 fbcon=font:TER16x32 nokaslr numa=off clk_ignore_unused pd_ignore_unused loglevel=7 panic=-1 rdinit=/init root=/dev/sda23 rootwait rootfstype=ext4 rw systemd.firstboot=no"
```

逐项说明：

- **保留 `rdinit=/init`**：initramfs 仍要跑，负责建 gadget + switch_root。带 initramfs 时内核会忽略 `root=`（只作为参数传给用户空间），不冲突。
- **`root=/dev/sda23 rootwait`**：UFS probe 在 12 s 左右完成，`rootwait` 必加（虽然实际是 init 脚本自己 mount，加上便于将来改成纯 root= 启动）。
  - 用 `sda23` 而不是 `PARTUUID=`：sda 是 LUN0、编号稳定（dmesg 里 23 个分区顺序固定）。想更稳的话首启后 `blkid /dev/sda23` 拿 PARTUUID，下次改 `root=PARTUUID=...`。
- **`console=tty0` 必须留**：`console=ttyGS0` 在 boot 时还不存在（gadget 是用户态建的），加了只会看到 "console [ttyGS0] not enabled" 的告警，没有收益 —— dmesg 从用户空间读即可。**想加也可以，无害但没用**。
- **`panic=-1` 必须留**：switch_root 失败时不要自动重启，留在 initramfs shell 里等你看日志。
- `systemd.firstboot=no`：阻止 systemd 首次启动交互式提问（我们已预置 hostname/machine-id）。
- `rw`：让 init 脚本按 rw 挂；systemd 的 `systemd-remount-fs` 再按 fstab 校一次。
- 若你打算走「不要 initramfs 直接 root= 启动」：**不要这么做**。没有 initramfs 就没有 gadget，没有 gadget 就没有 ttyGS0，**你将完全失去日志通道**（屏幕是关的、/dev/dri 是空的）。

---

## 7. initramfs 的过渡作用 + switch_root 正确顺序

保留现在的 1 MB initramfs，只改 `/home/shrp/ird/init`。骨架（在 v34 基础上加第 2 段）：

```sh
#!/bin/busybox sh
/bin/busybox --install -s /bin
mount -t proc none /proc; mount -t sysfs none /sys; mount -t devtmpfs none /dev
mkdir -p /dev/pts /tmp /newroot /sys/kernel/config /sys/kernel/debug
mount -t debugfs none /sys/kernel/debug 2>/dev/null
dmesg -n 1

# ---------- 1) gadget（acm console），必须在 switch_root 之前 ----------
mount -t configfs none /sys/kernel/config
G=/sys/kernel/config/usb_gadget/g1
UDC=$(ls /sys/class/udc/ 2>/dev/null | head -1)
mkdir -p $G/strings/0x409 $G/configs/c.1/strings/0x409 $G/functions/acm.usb0
echo 0x0525 > $G/idVendor; echo 0xa4a7 > $G/idProduct
echo M2468 > $G/strings/0x409/serialnumber
echo Meizu > $G/strings/0x409/manufacturer
echo "21Note mainline console" > $G/strings/0x409/product
echo ACM > $G/configs/c.1/strings/0x409/configuration
echo 250 > $G/configs/c.1/MaxPower
ln -sf $G/functions/acm.usb0 $G/configs/c.1/acm.usb0
[ -n "$UDC" ] && echo "$UDC" > $G/UDC
sleep 3
exec </dev/ttyGS0 >/dev/ttyGS0 2>&1        # 之后一切都从 USB 串口出

# ---------- 2) 等 UFS 分区出现 ----------
i=0; while [ ! -b /dev/sda23 ] && [ $i -lt 30 ]; do sleep 1; i=$((i+1)); done

# ---------- 3) 挂 rootfs 并 switch_root ----------
if mount -t ext4 -o rw,noatime /dev/sda23 /newroot 2>/dev/null && [ -x /newroot/sbin/init ]; then
    mkdir -p /newroot/proc /newroot/sys /newroot/dev /newroot/run /newroot/tmp
    mount --move /dev  /newroot/dev
    mount --move /proc /newroot/proc
    mount --move /sys  /newroot/sys        # 关键：configfs 一起搬走，gadget 不断
    exec switch_root /newroot /sbin/init
fi

# ---------- 4) 失败：留在 initramfs，保留 shell，绝不 panic ----------
echo "!!! rootfs 启动失败，留在 initramfs"
echo "    可手动: mount -t ext4 /dev/sda23 /newroot ; ls /newroot/sbin/init"
exec setsid cttyhack /bin/sh
```

### switch_root 的顺序与常见错误

正确顺序：**先 mount 新根 → 建好新根里的 proc/sys/dev/run → `mount --move` 三个伪文件系统 → `exec switch_root`**。

| 错误 | 后果 |
|---|---|
| 先 `umount /proc /sys /dev` 再 switch_root | **configfs 里的 gadget 被销毁 → ttyGS0 消失 → 你彻底失联**（这是最容易踩、代价最大的一条） |
| 忘了 `mount --move /sys` | 同上：gadget 随 configfs 卸载而解绑，串口消失 |
| `/newroot` 只是目录没挂东西 | `switch_root: not a mount point` |
| `/newroot` 挂成 `ro` | systemd 只读启动，一堆 unit 失败 |
| 不检查 `/newroot/sbin/init` 就 switch_root | `Attempted to kill init` → kernel panic，且**没有日志通道**（panic=-1 会挂住不重启，只能硬复位） |
| 忘了 `exec` | switch_root 返回后脚本继续跑，PID1 变成 shell，systemd 起不来 |
| 新系统里没起 getty | switch_root 成功但**没有任何交互**（看起来像死机；判据是 `systemctl` 命令有响应但屏幕/串口无提示符） |

**兜底建议**：在 `$CONFIG_CMDLINE` 里再留一个 `boot.mode=initramfs` 的开关，init 脚本开头判断，方便编一版「只进 initramfs」的调试内核。

---

## 8. systemd 在这个设备上的特殊配置

环境事实：**没有 RTC 电池**（时间可能停在 1970）、**没有 /dev/dri**（panel 驱动缺、屏幕是关的）、**唯一 console 是 ttyGS0**、**没有网卡**。

### customize-hook 里必须做的事（`/home/shrp/m2468-hook.sh`，$1 = rootfs 目录）

```sh
#!/bin/sh
set -e
R="$1"
echo m2468 > "$R/etc/hostname"
sed -i 's/^127.0.1.1.*/127.0.1.1\tm2468/' "$R/etc/hosts" 2>/dev/null || echo -e "127.0.1.1\tm2468" >> "$R/etc/hosts"
echo 5c1b7f102b7a4d349d0e1f2a3b4c5d6e > "$R/etc/machine-id"      # 预置，免得 systemd-firstboot 交互

cat > "$R/etc/fstab" <<'EOF'
UUID=5c1b7f10-2b7a-4d34-9d0e-1f2a3b4c5d6e /     ext4  defaults,noatime,errors=remount-ro 0 1
tmpfs                                     /tmp  tmpfs defaults,nosuid,nodev             0 0
EOF

ln -snf /usr/share/zoneinfo/Asia/Shanghai "$R/etc/localtime"
echo "Asia/Shanghai" > "$R/etc/timezone"

# 没有的硬件 / 会等的服务：全 mask
systemctl --root="$R" mask \
  systemd-timesyncd.service systemd-time-wait-sync.service \
  systemd-networkd.service systemd-networkd.socket systemd-networkd-wait-online.service \
  NetworkManager-wait-online.service bluetooth.service ModemManager.service \
  systemd-firstboot.service apt-daily.timer apt-daily-upgrade.timer \
  getty@tty1.service

systemctl --root="$R" set-default multi-user.target
systemctl --root="$R" enable fake-hwclock.service
systemctl --root="$R" enable serial-getty@ttyGS0.service
```
（`systemctl --root=` 只在 systemd ≥250 可用；WSL 的 Ubuntu 是 258，OK。不行就手工建 symlink：
`ln -sf /lib/systemd/system/serial-getty@.service $R/etc/systemd/system/getty.target.wants/serial-getty@ttyGS0.service`）

### 串口 getty 要自己写一个，别直接用 serial-getty@（重要）

`serial-getty@.service` 带 `BindsTo=dev-%i.device`：拔一次 USB 线，ttyGS0 消失 → getty 被**永久停掉**，插回来也没提示符，非常像「系统死了」。改用无 BindsTo 的自定义 unit：

```ini
# /etc/systemd/system/usbconsole.service
[Unit]
Description=USB ACM console on ttyGS0
After=dev-ttyGS0.device

[Service]
ExecStartPre=/bin/sh -c 'while [ ! -c /dev/ttyGS0 ]; do sleep 1; done'
ExecStart=-/sbin/agetty --autologin root --nohostname --keep-baud 115200,38400,9600 ttyGS0 vt102
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```
（`--autologin root` 是可选的；调试期建议开，省得每次敲密码。同时 `systemctl disable serial-getty@ttyGS0` 避免两个 getty 抢同一个 tty。）

### 其他必须知道的

- **时间**：`CONFIG_RTC_HCTOSYS=y` 会在 boot 时用 rtc0 设时间，但没电池，读到的是陈旧值甚至 0 → 1970。`fake-hwclock` 把上次时间存 `/etc/fake-hwclock.data` 并在启动时回灌，是目前最省事的方案。首启后手动 `date -s "2026-10-29 12:00:00"` + `fake-hwclock save`。**1970 会让 HTTPS 证书 "not yet valid"，apt/curl 全挂**。
- **无 /dev/dri**：不要装任何 DM/显示栈（gdm/sddm/plymouth 都不装）。`systemd-logind` 会因为没有 seat 报几条 warning，无害；想干净就 `NAutoVTs=0`、`ReserveVT=0`。
- **journald**：改 `Storage=volatile`（写 /run/log）或保持 persistent 都行；时钟错乱时按时间戳筛日志会很难受，用 `journalctl -b`。
- **kmemleak/内核 oops 的落盘**：装 `pstore`? 没有。建议开 `CONFIG_PSTORE_RAM` 之类未编；短期靠串口抓。可加 `systemd-journald` + `dmesg -w > /var/log/dmesg.log &` 做持久化。
- **cgroup v2**：内核 `CONFIG_CGROUPS=y`，systemd 走 v2，不用额外参数。
- **udev**：devtmpfs + udev 正常工作；ttyGS0 的节点由 devtmpfs 自动创建（即使不 `--move /dev` 也会重建，**但 gadget 必须还绑在 UDC 上**，所以 §7 的 `--move /sys` 还是不能省）。

---

## 9. 验证步骤（全部通过 COM16 执行）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\Administrator\AppData\Local\Temp\ksuwork\sh.ps1" `
  -Cmds "cat /proc/cmdline`nfindmnt /`nls -l /sbin/init`nuname -a" -WaitSec 5
```

按顺序看这几条（每条都写清「什么样算成功」）：

| 命令 | 成功判据 |
|---|---|
| `cat /proc/cmdline` | 能看到 `root=/dev/sda23 rootwait`（说明刷的是新内核） |
| `findmnt /` | `SOURCE=/dev/sda23`，`FSTYPE=ext4`，`OPTIONS` 里有 `rw` ← **这一条就是「rootfs 搬家成功」的判据** |
| `ls -l /sbin/init` | 存在，且指向 systemd（`/lib/systemd/systemd`） |
| `systemctl is-system-running` | 返回 `running` 或 **`degraded`（这个环境 degraded 是正常的）**；返回 `offline`/超时 = systemd 没起来 |
| `systemctl --failed` | 只应有个位数失败；若 `sysinit.target`/`basic.target` 失败才是真问题 |
| `journalctl -b -p err --no-pager \| tail -40` | 没有 `Failed to mount`、`Dependency failed` |
| `date` | 合理时间（不是 1970）；不是的话 `date -s ...` 后 `fake-hwclock save` |
| `df -h /` | 8.0G、可用几 GB |
| `ls -l /dev/ttyGS0 /dev/console` | 都在（说明 gadget 活着） |
| `free -h` | ~14 GiB |
| `gcc --version && echo 'int main(){return 0;}' > /tmp/t.c && gcc -o /tmp/t /tmp/t.c && /tmp/t && echo BUILD_OK` | 打印 `BUILD_OK` ⇒ 「能编译」达标 |
| `dmesg \| grep -iE "EXT4-fs.*sda23"` | 有 `mounted filesystem with ordered data mode` |

进阶（可选，确认扩容可行）：`e2fsck -f /dev/sda23 && resize2fs /dev/sda23 && df -h /` → 变成 380G 左右。

---

## 10. 回滚方案

**回 initramfs（最常用，10 秒）**

```powershell
fastboot flash boot_b "C:\Users\Administrator\Desktop\meizu21note_Mu\★可用基线_USB串口_20261029\Mu-fuxi6.img"
# 或 ★待刷_Mu_关屏.img
fastboot reboot
```
因为 cmdline 是编在 boot_b 里的内核里，**刷回旧 boot_b 就等于刷回 `rdinit=/init` 的 initramfs 启动**，与 sda23 上的内容无关。ESP/rawdump 不用动（v34/v35 都不变）。

**回 Android（必须多一步擦 userdata）**

```powershell
fastboot flash boot_b        boot.img
fastboot flash dtbo_b        dtbo.img
fastboot flash vendor_boot_b vendor_boot.img
fastboot -w                 # 关键：userdata 现在是 ext4，Android 要 f2fs+metadata 加密，必须重建
fastboot reboot
```
- `fastboot -w` 会重新格式化 userdata（ABL 侧做 f2fs），**sda23 上的 Linux rootfs 会没**，这是预期。
- 如果 `fastboot -w` 报错，先 `fastboot erase userdata` 再 `-w`。
- **不要**碰 metadata / super / persist 等分区，否则 Android 侧也起不来。

**数据风险的实话**：sda23 一格式化，Android 的用户数据（照片/微信等）就没了。做之前确认要么已备份、要么不在乎（这台机器目前是实验机）。

---

## 11. 执行清单（建议按这个顺序，含时间预估）

| # | 步骤 | 预估 | 备注 |
|---|---|---|---|
| 1 | WSL 装 `mmdebstrap qemu-user-binfmt binfmt-support android-sdk-libsparse-utils` | 2 min | aliyun 源有候选，已验 |
| 2 | 写 hook 脚本 → mmdebstrap 出 Debian trixie arm64 rootfs | 20–90 min | 要实测 binfmt 是否生效 |
| 3 | `tar` + `mke2fs -d` 出 8 GiB ext4 镜像，`e2fsck -fn` + loop 挂载检查 | 10 min | 命令已在 §2 实测跑通 |
| 4 | `img2simg` 转 sparse；拷到 C: | 2 min | |
| 5 | 改 `.config` 的 CONFIG_CMDLINE（§6 那串）→ `make Image` → 按老流程重做 boot_b | 10 min | **别改别的配置**，尤其别顺手开 `=m` |
| 6 | 改 `/home/shrp/ird/init`（§7）→ 重打 `initramfs.cpio.gz` | 5 min | |
| 7 | 进 fastboot：`fastboot flash userdata xxx.simg` + `fastboot flash boot_b 新Mu.img` | 1–5 min | 第 7 步是唯一未实测环节 |
| 8 | COM16 验证（§9） | 10 min | |
| 9 | 起不来 → §10 回滚，看 §7 的失败分支提示 | — | 全程不需要拆机 |

---

## 12. 未实测 / 需要你决策的点

**未实测（我不编，必须上机验）**
1. `fastboot flash userdata` 是否被 ABL 允许、`max-download-size` 到底多少 —— **决定主方案能不能成立**。不行就转 §5 方案 c。
2. WSL2 里 `qemu-user-binfmt` 注册 aarch64 是否成功（`ls /proc/sys/fs/binfmt_misc | grep qemu-aarch64`）。不行就用 `debootstrap --foreign` + 设备上原生 second-stage。
3. 4K 逻辑块设备上 1024/2048 块大小 ext4 的**具体**报错文本（结论确定是挂不上，报错文本我没实测）。
4. 8 GiB → 388 GiB 的 `resize2fs` 在这台 UFS 上的耗时/稳定性。
5. gadget mass_storage 模式下的实际吞吐（估 100–300 MB/s，没测）。

**需要你决策**
- **A. rootfs 版本**：Debian 13 trixie（工具链新、我推荐）还是 Debian 12 bookworm（更保守）？还是先上 Ubuntu base 24.04（28.5 MB，快，但没有 gcc）？
- **B. 镜像里要不要预装 build-essential**：预装 = 一次到位但 mmdebstrap 要多跑 30–60 分钟；不预装 = 首启快，但「能编译」要等第二条通道（离线 deb 或 WiFi）。
- **C. 镜像大小**：8 GiB（推荐，传输快、后续 resize）还是直接 32/64 GiB？
- **D. 传输通道**：直接赌 `fastboot flash userdata`，还是先花 20 分钟把 gadget mass_storage + Windows 裸写脚本准备好当 B 计划？（我建议两个都准备，脚本都在 §5）
- **E. 是否顺手把 `systemd.firstboot=no`、`--autologin root` 这类「方便调试、牺牲安全」的开关留在镜像里**（实验机建议留）。

---

## 附：本方案直接依赖的实测证据清单

- `/home/shrp/lmp73/.config`：`CONFIG_EXT4_FS=y`、`# CONFIG_F2FS_FS is not set`、`CONFIG_CMDLINE_FORCE=y`、`CONFIG_USB_CONFIGFS_MASS_STORAGE=y`、`CONFIG_USB_F_MASS_STORAGE=y`、`CONFIG_USB_MASS_STORAGE=m`、`CONFIG_CRYPTO_XTS=m`、`CONFIG_OVERLAY_FS=m`、systemd 所需 `CGROUPS/*_NS/SECCOMP/TMPFS_XATTR` 全 `=y`。
- `com16_capture.txt`：`sd 0:0:0:0: [sda] 124010496 4096-byte logical blocks (508 GB/473 GiB)`、`sda23` 存在、`Preferred minimum I/O size 524288 bytes`。
- `/home/shrp/initramfs.cpio.gz` = 1,007,180 B / 31 条目；busybox 内含 `switch_root chroot mke2fs fdisk losetup base64 gzip xzcat getty mdev reboot`。
- WSL：`mke2fs 1.47.2` 的 `-d` 目录模式与 `-d 未压缩 tar` 模式**均实测成功**（`-d .tar.gz` 失败）；`dumpe2fs` 确认 4096 块 + 64bit + metadata_csum；loop 挂载校验 OK；`sudo` 免密。
- 镜像可达性（`curl -I`）：TUNA/aliyun debian & ubuntu-cdimage & alpine 全部 200；`ubuntu-base-24.04.5-base-arm64.tar.gz` = 29,936,675 B；`alpine-minirootfs-3.22.7-aarch64.tar.gz` = 3,971,679 B。
- PC：`fastboot 36.0.0`、`mke2fs.exe 1.46.6`（带 `-d`）、`make_f2fs.exe`；C: 剩 103 GB；WSL /home 剩 812 GB。
