# 反方报告：panel2 启动失败不是「Mu 读大于 14MB 的 BOOTAA64.EFI 失败」

作者：反方/质疑者　时间：2026-10-29 12:2x　性质：只读分析（未刷机、未改源文件）

---

## 0. 结论（一句话）

**体积假设不成立，可以当场证伪——而且不需要刷机。**
但两轮诊断说「panel 驱动 / 内核配置」也不对：**12:11 那次失败里，panel2 的 panel 驱动根本不可能 bind**（面板 DT 是 Mu 的 FdtBlob 提供的，而 12:11 用的是旧 Mu+旧 DT）。真正的障碍是**同一份内核里 5 项 config 变化把「显示器/USB 控制台」和「启动」放进了同一个崩溃域**，失败形态是**内核静默挂死（不是加载失败）**，因此它和「Mu 读不到文件」在外部完全同形。见 §3、§4。

---

## 1. 体积假设的三条硬伤

### 1.1 命中率：同一体积区间里「成/败/成」交替，单调阈值在数学上不存在

我把每个 ESP 里的 `EFI/BOOT/BOOTAA64.EFI` 抽出来逐个量（7z + 自写 FAT32 链解析，两法互校）：

| 镜像 | BOOTAA64.EFI 字节 | 簇数(512B) | 结果 | 证据 |
|---|---|---|---|---|
| sp-v35（旧基线） | 10,977,792 | 21,441 | ✅ 多次 | 通篇使用 |
| esp-stable | **14,725,632** | 28,761 | ✅ 「UFS 好 + 稳定 60s+」 | 稳定版目录说明 |
| **esp-panel.img（10-28 17:34）** | **14,729,728** | 28,769 | ❌ **崩** | 状态交接 §四：「esp-panel.img 17:35 ❌ 崩」 |
| esp-v34 / v35-GPUCC | **14,733,824** | 28,777 | ✅ 有完整开机日志 | ★可用基线\开机完整日志.txt |
| esp-v17/v18 | 14,778,880 | 28,865 | （开发链主线） | — |
| esp-v19…v23 | 14,795,264 | 28,901 | （开发链主线） | — |
| v36/v37/v38/v39 | 14,864,896 | 29,033 | 未记录 | — |
| **panel1 / panel2** | **14,868,992** | 29,041 | ❌ 失联 ×2 | 12:00 / 12:11 |

**决定性一行**：14,725,632 ✅ → 14,729,728 ❌ → 14,733,824 ✅。
三者相差 **4KB 和 4KB**，结果却是「成、败、成」。任何「体积阈值」都要在 4KB 内先败后成再败，物理上不可能。所以体积不是变量，**内容**才是；panel1/panel2 的 14.868MB 失败也同理不能用体积解释。

（面板方向的历史控制组还给出同一个结论：10-28 17:34 的 `esp-panel.img` 只把 DT 里 panel/display 的 `status="disabled"` 去掉，EFI 14,729,728，一样崩 → 显示路径一「接通」就死，与体积无关。）

### 1.2 从 Mu 视角看，两个镜像是「同一个文件系统、同一条连续簇链」

FAT 结构逐项比对（自写解析器，读 BPB + FAT + 目录项）：

| 项目 | v34（✅） | v39（未记录） | panel1/panel2（❌） |
|---|---|---|---|
| bytes/sector, sec/cluster | 512 / 1 | 512 / 1 | 512 / 1 |
| 总扇区 / 簇数 | 524,288 / 524,288 | 同 | 同 |
| FAT 大小 / 份数 | 4,033 扇区 / 2 | 同 | 同 |
| 卷标 / 根簇 | MUESP / 2 | 同 | 同 |
| EFI 起始簇 | **139,483** | **139,483** | **139,483** |
| 碎片段数（extents） | **1（完全连续）** | **1** | **1** |
| 尾部 slack | **0** | **0** | **0** |

即：给 Mu 看的差异只有「多 264 个连续 512B 簇」。没有碎片、没有跨链、没有几何差异——一个按簇链顺序读的 FAT 读盘器在这两个文件之间没有任何可分辨的「断层」。

### 1.3 源码里唯一存在的硬上限，比已经能启动的基线还小

`Platforms/Meizu/m2468Pkg/Drivers/UfsWakeDxe/UfsWakeDxe.c`：

- `#define KERNEL_MAX_BYTES 0x4000000UL  // 64 MiB ceiling`  → 64MB，远大于 14.87MB；
- `#define STAGE_BYTES_MAX 0x00DE6200UL  // vmlinuz.efi size`  → **14,574,080**，比已能启动的 14,733,824 **小 159,744 字节**；
- `STAGE_BYTES_MAX` 全文只出现在定义处（`grep` 只命中 1 行），是死常量；
- 该文件里的 `DeliverKernel`（bare-jump 直跳 arm64 Image 的老路）**在源码里查不到实现，只有注释引用**；而当前实际启动是 EFI-stub 路：开机日志第一行就是 `efi: EFI v2.7 by Project Silicium` + `earlycon: efifb0`，说明内核是作为 EFI 应用被 LoadImage/StartImage 起来的。EDK2 `LoadImage` 按文件大小 `AllocatePool`，没有恒定上限。

**所以代码里不存在一个能卡在 14.8MB 的闸门；即使有，那个值（14,574,080）也低于已成功启动的基线，早就该炸。**

### 1.4 顺手排除「ESP 写坏了 / rawdump 没写进去」

- panel1、panel2 里的 EFI 与构建产物逐字节相同：`md5 560069130d8ba01684620e4cc1a81a0e` == `arch/arm64/boot/vmlinuz.efi`（12:10 产物）。镜像本身是**完整、忠实**的构建输出，不是截断/错位。
- FAT 解析显示文件 size 字段、簇链、slack 全部自洽（见 1.2）。
- `getvar partition-size:rawdump` 返回 0 是 getvar 的老毛病；同一个分区在 12:05、12:14 用**同一条 fastboot 命令写 256MB 成功**并立刻从它启动，说明分区可写、写入路径可用。
- **唯一从未验证的环节**：从来没有 read-back 过 rawdump 的实际内容（刷完就启动，没做 `dd | md5`）。这是流程漏洞，但它是**随机性**故障源，无法解释「3 次 panel 写全失败 / 3 次 v35 写全成功」这种与内容强相关的模式。

---

## 2. 两轮诊断漏掉的两个事实

### 2.1 面板 DT 不在 ESP 里生效——它来自 Mu 的 FdtBlob

- `稳定版_UFS可用_20261028\verify_dtb.sh` 的判据是「dtb ≡ Mu FdtBlob ≡ Mu 产物」，不一致就打「刷了也不生效」；
- 11:58 的 `panel_build.log` 第 5 步写着 **「重编 Mu（dtb 变了，必须同步）」**；
- arm64 EFI zboot 若带 appended DTB 会覆盖固件 DT，但本镜像 `.data` 段只有 **512 字节**，装不下 134,586B 的 dtb → 没有 appended DTB，内核只能吃 EFI 配置表里的 DT，即 **Mu 的 FdtBlob**。

**推论（这是本轮最硬的一刀）：12:11 那次是「旧 Mu（DT 里 panel@0 compatible = "boe,meizu20-amoled-fhd"）+ panel2 内核（驱动 match "meizu,m2468-panel"）」。旧 DT 里没有任何节点叫 meizu,m2468-panel，而 `CONFIG_DRM_PANEL_BOE_MEIZU20` 在 config 里是 `# not set` —— 也就是说 panel2 的 panel 驱动在 12:11 这次启动里根本没机会 bind，是彻底的惰性代码。**

所以：「panel2 失败 = panel 驱动问题」在 #2 这次实验里 **不成立**（驱动没跑）；「panel2 失败 = 体积」也没有机制（§1）。两个流行解释同时死掉。

### 2.2 失败内核与可用内核的真实差异只有 5 项 config（已逐条列出）

`config.good_1740.txt`（esp-stable/v 系列的食物）vs 当前 `.config`（panel 构建），排除 `# ... is not set` 注释后 **只有 5 项实体差异**：

| 项 | 旧（✅能启动） | 新（❌panel 构建） | 影响面 |
|---|---|---|---|
| `CONFIG_DRM_PANEL_MEIZU_M2468` | 无 | **=y** | 面板驱动编进内核（但 §2.1 说它 bind 不上） |
| `CONFIG_SM_DISPCC_8550` | **=m** | **=y** | 显示时钟控制器进内核：从「initramfs 里没 modprobe → 永不加载 → mdss/dsi 干净地 -110 推迟」变成「开机即实例化并在唤醒前触碰寄存器」 |
| `CONFIG_SM_GPUCC_8550` | =m | =y | 已单独验证无害（v35_GPUCC 能启动） |
| `CONFIG_PHY_QCOM_QMP_USB` | =m | **=y** | USB PHY 进内核 |
| `CONFIG_PHY_SNPS_EUSB2` | not set | **=y** | 新增 eUSB2 中继 PHY 驱动（唯一控制台通道上的新变量） |
| `CONFIG_USB_G_SERIAL` | =y | not set | 无害：initramfs 走 configfs `acm.usb0`，靠 `USB_CONFIGFS_ACM/USB_F_ACM=y`（两版都在） |

`DRM_MSM=y`、`DRM_MIPI_DSI=y`、`DRM_MSM_DSI=y` 两版都是 y —— 显示栈一直是编进内核的，只是**一直没有东西让它真正跑起来**（无 panel 匹配 + dispcc 缺席 → `-110`）。

### 2.3 附带发现（不是本次失败原因，但会浪费下一次实验）

所有 ESP 里的 `initramfs.cpio.gz` 都是同一个：1,006,305B / `md5 667cf168…`。而 11:37 重做的 initramfs 是 **1,139,134B**（`/home/shrp/initramfs.cpio.gz`，含 v39 的 chroot 逻辑）。**它从来没被打进任何 ESP**——v39「ubuntu」这个名字是假的，实际跑的仍是旧 init。同理 panel1/panel2 也带旧 init。

---

## 3. 真正的障碍（我的判断）

**障碍不在 Mu、不在 ESP、也不在「panel 驱动写得对不对」，而在这条链上没有「失败的隔离带」：**

```
ABL 显示活着(0xB8000000) → Mu 装 DT、LoadImage 内核 → 内核 early init
        → clk(drv dispcc=y) / drm(msm=y) / dsi / phy 全部 built-in
        → 一直到 initramfs 的 init 才把 USB acm gadget 立起来 = 唯一控制台
```

1. 只要显示/USB 侧任何一步在「init 之前」把 SoC 拖住（唤醒前访问已掉电 GDSC、DSI PHY PLL 等 dispcc 时钟、或新增 eUSB2 PHY 抢了 dwc3 的 PHY），**控制台就永远不会出现**；
2. 而控制台恰恰是唯一的观测手段，于是「内核挂在 DRM 里」与「Mu 停在 BDS 没加载内核」在 PC 侧**完全同形**——这就是两次失联被误读成「镜像/加载问题」的根源；
3. 这也解释了为什么「假驱动（panel1）」和「真驱动 FAKE 模式（panel2）」都死：**死的不是驱动逻辑，是「显示路径被接通」这件事本身**（10-28 17:34 的 `esp-panel.img` 只改了两个 `status`，同样崩，是同一个模式）；
4. 它是一个**hang**，不是**load failure**——所以「体积」「写入」「FAT」全都解释不了它，也永远修不好它。

一句话：**当前内核把「显示器的电源/时钟域」和「唯一的串口控制台」绑在同一次初始化里，任何一次面板尝试都在拿控制台当赌注。**

---

## 4. 验证实验（每步都可证伪，代价从 0 开始）

### T0（零成本、1 分钟、先做这个）——用「屏幕」判断是 loader 死还是内核挂

ABL 的 framebuffer 在 0xB8000000 仍然活着，内核 `earlycon=efifb0` 会**直接往屏上打内核日志**（开机日志第 6 行就是这个）。

- 先确认基线（当前 esp-v35/v34）启动时**屏上能看到内核滚动文本**；
- 若是：下一次失联时看屏——
  - 屏上是内核文本（哪怕停在某一行）→ **内核跑了，loader 无罪，体积假设当场死亡**；
  - 屏上是黑的/停在 ABL logo 不动 → loader/BDS 卡住 → 体积假设复活，进 T1。
- 若基线屏上也什么都没有（面板无驱动，可能全程黑）→ 此路不通，直接进 T1。

> 这条的价值：它把「同形的两种死法」分开，而且不需要任何刷机。

### T1（一次刷机、可自退）——把体积和内容彻底分开

**做法**：拿现在设备上这份能启动的 `★待刷_v35_GPUCC.img`，把 `BOOTAA64.EFI` 尾部补零到 **panel2 的精确大小 14,868,992**（补 135,168 字节 = 33 页），其余一个字节不动。

```bash
# 只需在 WSL 里跑，不碰设备
cd /home/shrp && rm -rf padtest && mkdir padtest && cd padtest
7z x "/mnt/c/Users/Administrator/Desktop/meizu21note_Mu/★待刷_v35_GPUCC.img" EFI/BOOT/BOOTAA64.EFI
truncate -s 14868992 EFI/BOOT/BOOTAA64.EFI      # 14,733,824 -> 14,868,992
# 校验：PE 头 / zboot 头字段必须没变（payload_off=98816, payload_size=14623215,
#       .text 结束 14733312, .data 512B @14733312；新增字节全在最后一个段之后）
python3 -c "d=open('EFI/BOOT/BOOTAA64.EFI','rb').read();import struct;
print(len(d), d[:4], struct.unpack_from('<I',d,8)[0], struct.unpack_from('<I',d,0xc)[0])"
cp "/mnt/c/Users/Administrator/Desktop/meizu21note_Mu/★待刷_v35_GPUCC.img" esp-sizetest.img
7z a -t# esp-sizetest.img 2>/dev/null || true   # 或用现成的 ESP 打包脚本原地替换该文件
```

**为什么这个补零是「惰性」的**：镜像是 PE/COFF + zboot 头（`MZ`/`zimg`/`zstd`），加载器按 PE 段表和 `payload_size` 取数据；最后一个段 `.data` 在 14,733,312–14,733,824，**之后追加的字节没有任何结构引用它们**。Mu 仍然要老老实实读 14,868,992 字节的 FAT 文件（这正是要施加的压力），而内核内容 100% 不变。

**判定（一刀两断）**：
- 能启动（COM16 起来，`uname -v` 仍是 v35 的构建时间）→ **体积假设正式死亡**，panel2 的失败 100% 来自内核内容（进 T2）；
- 不能启动 → **体积假设成立**，且立刻给出工程解：不是「把内核压小」，而是「让 payload 不走 FAT 读取路径」（塞 `boot_a` 用 mkbootimg 布局，Mu 的 UfsWakeDxe 本来就有读 boot 分区的代码）。

**回滚**：`fastboot flash rawdump "★待刷_v35_GPUCC.img"` —— 就是现在设备上那一份（md5 可先比对），一行命令、今天已成功回滚 3 次。

### T2（仅在 T1 通过后，1 次刷机）——拆 5 项 config，只留一个变量

用同一份 v35 源码，**只把 `SM_DISPCC_8550` 改成 =y**，panel 驱动不加、DT 不动、USB PHY 项不动，编出 `esp-dispcc.img`：
- 崩 → dispcc=y 是凶手（显示时钟控制器在唤醒前碰寄存器），panel 驱动彻底洗清；
- 不崩 → 换 `PHY_SNPS_EUSB2=y + QMP_USB=y` 单独测（唯一控制台通道上的新增 PHY）；
- 两者都不崩 → 才轮到「确实需要 panel 驱动 + 匹配 DT 同时在场」的组合（此时也已经知道是 bind 之后，而不是加载）。

---

## 5. 对「再刷一次 panel2 试试」的明确否定

不需要，也别做：**它没有任何判别力**。
- 若失败 → 只能重复已知结论（"panel2 死"），仍分不清 loader 还是内核；
- 若成功 → 说明是随机写坏，但同一命令已连续成功 3 次，无法归因。

---

## 6. 附：本次核对用到的原始数字（可复算）

- ESP 卷：`bps=512 / spc=1 / tot32=524,288 / FATsz32=4,033 / nfat=2 / root=2 / label=MUESP`，空闲 236.8MB；
- `BOOTAA64.EFI`：起始簇 139,483（字节偏移 ≈ 71.6MB），**1 段连续**，slack 0（全部 8 个样本一致）；
- panel2 EFI == `arch/arm64/boot/vmlinuz.efi`（12:10 构建）：`md5 560069130d8ba01684620e4cc1a81a0e`，14,868,992B；
- panel1 EFI：`md5 1a88bb2e…`（假驱动 295 行，符号 `m2468_fake_probe/prepare/get_modes/enable/remove`，panel_build.log §3）；
- panel1/panel2 的 `dtb`：`md5 f8add8c5…`，与 `FdtBlob.bak_1220` 一致；与可用 DT `3ab8d7c5…` 的**全部差异只有一行**：
  `panel@0 { compatible = "boe,meizu20-amoled-fhd" → "meizu,m2468-panel" }`（反编译 7,820 行逐行 diff）；
- v34/v35/v39/v36 的 dtb 均为 `3ab8d7c5…`（未变）；
- Mu 侧：`★待刷_Mu_关屏.img`（01:10，`md5 b01ee2ce…`）在 12:05、12:14 两次回滚中未变 → **12:11 失败与 12:14 成功用的是同一个 Mu**，Mu 不是变量；
- 构建日志：`FVMAIN [99%Full] 6356992 total, 6355560 used, **1432 free**` —— 这是**构建期**风险（再加任何东西 GenFv 会硬报错，不会静默），与 12:11 无关（那次用的是旧 Mu）。但 12:00 那个"新 Mu"已被覆盖（`★待刷_Mu_panel.img` mtime 12:20，`FdtBlob.bak_1220`=panel dtb，现行 FdtBlob=`8f81b0df`），**12:00 那次的 Mu 已无法原样复现**——这也是「12:00 失联」不能当证据用的原因。
