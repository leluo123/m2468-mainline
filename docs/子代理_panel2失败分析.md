# panel2 内核启动失败 —— 归因分析（只读审计）

时间：2026-10-29 12:30　范围：`panel-meizu-m2468.c` / `ili7838e_seq.h` / Kconfig / Makefile / .config / panel1↔panel2 镜像字节对比 / dtb
约束：全程只读。未改任何源文件、未改 .config（`md5 448c83515ac5bbd2fd1eb15f3222aa71` 前后一致）、未刷机。

---

## 0. 结论先行

1. **驱动无罪，而且不是"概率上无罪"，是物理上不可能执行。**
   两个候选 dtb 里 `panel@0` 都是 `status = "disabled"`：
   - boot_b（01:10 关屏 Mu）内嵌 dtb `896b1ae2…`：`compatible = boe,meizu20-amoled-fhd`，`status = disabled`
   - panel1/panel2 镜像里的 ESP `dtb` 文件 `f8add8c5…`：`compatible = meizu,m2468-panel`，`status = disabled`
   而 12:19 从设备上抓到的 `/proc/device-tree/.../panel@0/` 正是 `compatible=boe,meizu20-amoled-fhd`、`status=disabled`。
   → `of_platform_populate()` 会跳过 disabled 节点，**panel 设备根本不会被创建，`m2468_probe()` 永远不会被调用**。
   驱动匹配表（`meizu,m2468-panel`）、Kconfig、552 行 seq 头、regulator 保护，全部在这场失败里**一次都没执行过**。

2. **panel2 相对 panel1 的改动只有一样东西：内核字节流。**
   256MB ESP 镜像逐页对比：唯一差异是 `0x480F600` 起的 `BOOTAA64.EFI`（14,868,992 B，单段连续 29,041 簇）＋两个目录项时间戳扇区。
   引导扇区/BPB、两份 FAT、`dtb`(md5 `f8add8c5…`)、`initramfs.cpio.gz`(md5 `667cf168…`) 全部逐字节相同。没有分区/引导结构层面的改动。

3. **真正与"失败"相关的是内核尺寸档位，不是面板驱动。**
   | 镜像 | BOOTAA64.EFI | zstd payload | 解压后 vmlinux.bin | 结果 |
   |---|---|---|---|---|
   | v35 (esp_v35.img) | 10,977,792 | 10,867,371 | **30,408,704** | 能启动（COM16 可用） |
   | v36 / v37 / v38 / v39 | 14,864,896 | ~14,756,9xx | — | 未确认 |
   | panel1 | 14,868,992 | 14,757,547 | 47,972,352 | 未确认 |
   | **panel2** | 14,868,992 | 14,759,131 | **47,972,352** | **完全失联** |
   | panel3 | 14,868,992 | 14,759,131 | 47,972,352 | 待测（内核与 panel2 **完全相同**）|

   两个内核解压后**尺寸一模一样**（47,972,352），只差内容；而 v35 能跑、14.76MB 档全灭。这条相关性比"驱动"强得多，且能解释"为什么换驱动之前 v36–v39 就已经不行"。

4. **失败的可见性也解释得通**：`CONFIG_CMDLINE` 里只有 `console=tty0 earlycon=efifb keep_bootcon`，**没有 ttyGS0**；COM16 是 initramfs 的 `/init` 用 configfs 现场建 acm gadget 弄出来的（`/home/shrp/ird/init` 第 20–37 行）。
   加上 `panic=-1` 且 `CONFIG_PANIC_TIMEOUT=0`（.config:11772）→ 内核在 `/init` 之前任何位置挂掉，都表现为：**无 COM16、黑屏、不自动重启、只能长按进 fastboot**。这与观测现象逐条吻合，也说明"没日志"不等于"没启动到更早的阶段"。

---

## 1. 逐行审计 `panel-meizu-m2468.c`（442 行，不是 440）

### 1.1 probe 之外会执行的代码（问题 1 的答案）

整份文件的"启动期可执行面"只有三块，全部安全：

| 位置 | 内容 | 何时执行 | 风险 |
|---|---|---|---|
| 行 41 | `#include "ili7838e_seq.h"` | 编译期 | 无（纯常量）|
| 行 86–115 | `static const struct drm_display_mode m2468_modes[]`（2 项，全常量表达式）| .rodata | 无 |
| 行 424–438 | `of_device_id[]` + `module_mipi_dsi_driver()` | device_initcall | 见下 |

`module_mipi_dsi_driver(m2468_driver)` 展开链：
`module_driver(drv, mipi_dsi_driver_register, mipi_dsi_driver_unregister)`
→ `static int __init m2468_driver_init(void){ return mipi_dsi_driver_register(&m2468_driver); }` + `device_initcall(...)`。
注册只做 `driver_register(&drv->driver)`：把 driver 挂到 mipi-dsi 总线链表上，然后对总线上**已存在**的设备尝试 bind。此刻（device_initcall 阶段）panel 设备不存在（节点 disabled），于是**只有链表插入，没有任何硬件访问、没有任何 dev_* 资源申请**。不可能 panic。

`.text.unlikely` 里的三个克隆（System.map 实证，说明这段代码确实被链接进可用映像，不是"被优化掉"）：
```
ffff800080025dd8 t m2468_unprepare.part.0     ← m2468_remove 的特化副本
ffff800080025e8c t m2468_enable
ffff800080025f40 t m2468_disable
ffff800080b0bd0c t m2468_probe
ffff800080b0bfe0 t m2468_prepare
ffff800081a23710 d m2468_panel_funcs
```
它们只在 `drm_panel_enable/disable/unprepare()` 被调用时执行——也就是"有 panel 设备且 DRM 走到点亮"之后，与"initramfs 之前"完全无关。

### 1.2 `devm_drm_panel_alloc()` 用法（问题 2 的答案：正确）

本内核 `include/drm/drm_panel.h:318-321`：
```c
#define devm_drm_panel_alloc(dev, type, member, funcs, connector_type) \
	((type *)__devm_drm_panel_alloc(dev, sizeof(type), \
					offsetof(type, member), funcs, \
					connector_type))
```
调用（行 346）：`devm_drm_panel_alloc(dev, struct m2468_panel, panel, &m2468_panel_funcs, DRM_MODE_CONNECTOR_DSI)`
→ `sizeof(struct m2468_panel)`、`offsetof(struct m2468_panel, panel)`（=0，因为 `panel` 是第一个成员）。
**类型名写的是完整 `struct m2468_panel`，展开正确。**
补充两点：
- 若写成 `m2468_panel`（不带 struct）→ 编译报错，不会"算错偏移"，所以这个坑不存在；
- 真正要注意的是**不要在成员名前写点**（`ctx->panel`），这里也没有。
结论：这条路径没有偏移/越界问题，也不会在注册阶段执行。

### 1.3 `ili7838e_seq.h`（552 行，37KB）（问题 3 的答案：无害）

- 结构：`#ifndef` 保护 + 5 个 `static const u8` 数组：
  `ili7838e_on_120hz`(行10)、`_144hz`(113)、`_90hz`(216)、`_60hz`(319)、`_30hz`(437)，行 550 收尾，552 行 `#endif`。
- 全部 `const` → 落 `.rodata`，不进 `.data`，不产生任何运行期构造/初始化代码；内核镜像体积增加约 5–6KB（实测 payload 只涨 1,584 B，压缩后）。
- 只有 `ili7838e_on_60hz` 被引用（驱动行 247），其余 4 个是 `-Wunused-const-variable` 噪音（GCC 对 `static const` 数组只警告、不报错，也不会被丢进异常段）。
- 而且是否引用取决于 `ctx->mode == M2468_MODE_REAL`，而 **REAL 当前不可达**：行 356 默认 `M2468_MODE_FAKE`，行 357–360 的分支里两个赋值都是 FAKE（`if (!strcmp(mode_str,"fake")) ctx->mode = M2468_MODE_FAKE;`），没有任何路径写 `M2468_MODE_REAL`。
  → 即使面板被 enable，这个驱动也一帧 DSI 命令都不会发。**"发错初始化序列把屏/DSI 搞死"这条可能性被代码本身排除了。**

### 1.4 Kconfig / Makefile（问题 4 的答案：合法）

- `drivers/gpu/drm/panel/Kconfig:623-630`，插在 `config DRM_PANEL_NEWVISION_NV3052C`(614) 与 `config DRM_PANEL_NOVATEK_NT35510`(632) 之间，`tristate` + 制表符缩进 + `depends on OF / DRM_MIPI_DSI / BACKLIGHT_CLASS_DEVICE`，语法与邻居一致。
- **实测验证**（不碰真 .config）：
  ```
  cp .config /tmp/kc_val && make -s KCONFIG_CONFIG=/tmp/kc_val olddefconfig
  ```
  解析零报错（rc=0），跑完 `.config` md5 仍是 `448c8351…`。Kconfig 语法无问题。
- `.config` 与 panel1 那次构建用的 `.config.pre_panel`（md5 `11bf84be…`）**逐行 diff 只有 2 行**：`CONFIG_DRM_PANEL_MEIZU_M2468=y` 从第 11943 行挪到第 6303 行（因为 Kconfig 条目换了位置）。**选项集合完全相同**——这本身就否掉了"改配置把别的驱动关掉"这类猜想。
- Makefile:141 `obj-$(CONFIG_DRM_PANEL_MEIZU_M2468) += panel-meizu-m2468.o`，正常。

### 1.5 顺带查出的真实缺陷（都不会在启动阶段执行，但迟早要修）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| D1 | 行 356–360 | `M2468_MODE_REAL` 不可达，DT 写什么都进不了 REAL | 功能形同虚设，"两层保护"其实是"永远 FAKE" |
| D2 | 行 144 | `case 0x05: mipi_dsi_dcs_write_buffer(dsi, payload, 0)` | 短写命令（DCS 命令本身在 payload[0]）长度应为 1，传 0 等于什么都不发 |
| D3 | 行 417–422 | `m2468_remove()` 只用 `mipi_dsi_get_drvdata()` 取 ctx，probe 失败时该值为 NULL | 仅 unbind 路径，NULL 解引用 |
| D4 | 行 364–367 | `of_property_match_string(dev->of_node, "regulator-names", "vddio")` 结果被丢弃 | 死代码，误导读代码的人 |
| D5 | 缺 `#include <linux/string.h>` | `strcmp()` 靠 `<linux/module.h>` 间接带入 | 换内核版本可能炸 |

---

## 2. panel1 → panel2 到底改了什么（字节级证据）

### 2.1 ESP 镜像（`★待刷_panel1.img` b7079138… vs `★待刷_panel2.img` ab955210…，各 268,435,456 B）

4KB 页级 diff，全部差异集中四处：
```
0x3f4000                 1 页   ← 根目录项（时间戳）
0x3a7e000                1 页   ← EFI/BOOT 目录项（时间戳）
0x480f000–0x4816000      7 页   ← BOOTAA64.EFI 头部
0x4817000–0x563d000   3622 页   ← BOOTAA64.EFI 主体
```
即：**除内核 EFI 文件外没有任何字节变化。** 进一步核对：
- 引导扇区 0–0x200：相同；备份引导扇区（sector 6）：相同；BPB 字段：相同
- FAT1 == FAT2（两镜像内部都一致）；FAT1(p1) == FAT1(p2)；FAT2(p1) == FAT2(p2)
- 文件占位：两镜像里 `BOOTAA64.EFI` 都从 **0x480F600** 开始，`cluster size = 512 B`，单段连续 29,041 簇，未碎片化、未换位置
- `dtb` 文件 mtime 变了但 **md5 相同**（`f8add8c5b7e1aaa1d96471d49b365ec8`，134,586 B）
- `initramfs.cpio.gz` md5 相同（`667cf168bd01e65608b6e0c0c6abc93d`，1,006,305 B）

### 2.2 内核 payload

从 zboot 头（`MZ\0\0zimg`，"zimg" @ +4，`payload_offset=0x18200`）取出并 zstd 解压：
```
panel1 payload 14,757,547  → vmlinux.bin 47,972,352  B
panel2 payload 14,759,131  → vmlinux.bin 47,972,352  B   (差 +1,584 B 压缩后，解压后同尺寸)
ESP 里 BOOTAA64.EFI md5: panel1 1a88bb2e… / panel2 56006913…
```
panel2 的 vmlinux.bin md5 = `638fe72c1a18d40a8dfbc55a14cf7c21` = 内核树里 `arch/arm64/boot/vmlinux.bin`，字符串里有 `ILI7838E panel registered`、`meizu,m2468-panel` → 确认新驱动**确实编进映像了**（编译无误，链接无误）。

### 2.3 由此得到的关键推论

panel1 与 panel2 的内核，**除驱动代码 + 因它引起的重定位外没有差别**；而驱动在 dtb 层就被 disabled 屏蔽了。所以两者在内核侧对"能否跑起用户态"这件事**完全等价**。→ 驱动不可能是 panel2 失败的原因（否则 panel1 也该失败，或者 panel1 从来没成功过——这一点必须澄清，见 §4 第 0 步）。

---

## 3. 第 5 问的正向论证（drivers 到底该不该背锅）

原始假设（「dtb compatible 是 `boe,meizu20-amoled-fhd`，驱动只匹配 `meizu,m2468-panel`，所以驱动不会 probe，失败一定不是驱动引起的」）**结论成立，但论据要修正/加强两处**：

1. **不只是"不匹配"，而是"节点被关掉"。** 即使 compatible 一致（ESP 的 `f8add8` 就是 `meizu,m2468-panel`），`status = "disabled"` 也让 of 核心不创建平台设备。这比匹配失败更强：匹配失败至少还会有设备、只是 probe 不被调用；disabled 是连 `struct device` 都没有。
2. **"dtb 走 Mu 的 EFI configuration table，ESP 的 dtb 文件不用"这一点有旁证但不能百分百坐实。** 旁证：12:19 的设备抓取显示 `compatible = boe,meizu20-amoled-fhd`，而当时 ESP 里的 `dtb` 文件是 `meizu,m2468-panel`（`f8add8`）——运行期看到的 compatible 与 ESP 文件**不一致**，说明内核拿到的是 Mu 内嵌的那份（`896b1ae2`）。
   遗留的不确定性：v35 的 ESP `dtb` 也恰好是 `boe + disabled`（`cae124e7`），所以在"最后一次刷的是 v35"的情况下两种解释都能对上。**要一次性排除**：在 dts 里加一个无害的自定义属性和唯一取值（例如 `meizu,dtb-probe = "from-mu-<时间戳>"`），重编 Mu 与 ESP 各放不同值，然后 `cat /proc/device-tree/meizu,dtb-probe` —— 一次就能判定谁说了算。
3. **真正该被怀疑的是"内核尺寸档位"，不是驱动。** 见 §0.3 表格：v35（payload 10.87MB / 解压 30.4MB）最后一次被证实在跑；14.76MB 档（v36…panel3）无一确认能启动，而 panel2 的驱动在 dtb 层面是死的。

---

## 4. 下一步验证（按"信息量/代价"排序，先做不伤设备的）

**第 0 步（必须先做，否则后面全是瞎猜）：把"panel1 到底跑没跑起来"钉死。**
现在无法从产物判断 panel1 是否被真正验证过。若 panel1 也没起来，那整条时间线的断点在 v35→v36（10:38），与驱动无关，后面所有 panel 工作都建在错误前提上。
判据：12:00–12:10 之间是否有过 COM16 会话/屏幕有输出。

**第 1 步（单变量、最干净、不需要新内核）：做一个"假大"镜像。**
把 v35 那份 `vmlinuz.efi`（payload 10.87MB，已被证明能启动）**原样复制**到 `EFI/BOOT/`，但在文件尾部补 0 填充，让 `BOOTAA64.EFI` 的文件大小变成 14,868,992 B（zboot 头里的 `payload_size` 不变，stub 只按 header 解压，尾部 padding 会被忽略）。
- 若**失联** → 坐实"Mu/FAT 层的文件大小或簇数上限"，与内核内容无关；
- 若**正常启动** → 排除文件大小，问题在真实内核（解压后 47.97MB 的内存布局），进入第 3 步。
这个实验只改 ESP 里一个文件，内核一行不动，且回滚成本 = 重刷 v35。

**第 2 步（并行做，零风险）：把 ESP 从 512B 簇改成 4KB 簇。**
当前 256MB 卷用了 1 sector/cluster → 14.87MB 文件需要 **29,041 簇**（v35 只需 21,441）。重建卷时用 4KB 簇，簇数掉到 ~3,630，其它（文件、内核、dtb）保持不变。若这一步就能启动，说明是 Mu FAT 驱动的簇链/读放大问题，比降内核体积省事得多。
注意：`mkfs.fat` 重建后要核对卷标签 `MUESP`、卷 ID、以及 boot_b 的 Mu 是否靠 GUID/PARTLABEL 找分区。

**第 3 步（若确认是内核体积）：把 payload 压回 <11MB。**
最肥的一块是**内建 initramfs**（`CONFIG_INITRAMFS_SOURCE="/home/shrp/initramfs.cpio.gz"`，1.14MB 源 + busybox 2.2MB，解压后约 3.3MB 进内核）；ESP 里本来就有 `initramfs.cpio.gz`，改由 Mu 通过 EFI initrd table / `initrd=` 传更合理。
其余可砍：`DRM_MSM_MDP4/MDP5`（本机 SM8550 只用 DPU）、不用的 panel 驱动、`CONFIG_DEBUG_INFO*`（不影响 Image 但影响 zboot 前处理）、`KALLSYMS` 仅保留必要项。
（只在本地核减，不改树——本报告未做任何修改。）

**第 4 步：只有内核能在"面板 disabled"下稳定启动后，才轮得到驱动。**
顺序必须是：先 12:20 的 `★待刷_Mu_panel.img`（dtb `8f81b0df…`，`status=okay`）刷 boot_b，**再**刷含 `status=okay` dtb 的 `★待刷_panel3.img`。只刷 ESP 不刷 boot_b 的话，Mu 内嵌 dtb（disabled/boe）仍然说话，panel3 等于 panel2，白测一次。
另外提醒：`meizu,panel-mode` 属性在 dts 里根本没写，而驱动 REAL 不可达（D1）→ panel3 即使绑上驱动，也只是把 3 路 regulator 打开、toggle reset、注册一个 1264x2780 的 mode，**不发任何 DSI 命令**。所以 panel3 成功只证明"card0 能起来"，证明不了屏能亮；要测初始化序列得先修 D1。

---

## 5. 复现本报告结论的命令

```bash
# dtb 侧（任一 Mu/ESP 里的 dtb）
fdtget -t s <dtb> /soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0 compatible
fdtget -t s <dtb> /soc@0/display-subsystem@ae00000/dsi@ae94000/panel@0 status

# 镜像差异（只比内核）
python3 - <<'EOF'
d1=open("★待刷_panel1.img","rb").read(); d2=open("★待刷_panel2.img","rb").read()
P=4096; print([ (hex(i*P)) for i in range(len(d1)//P) if d1[i*P:(i+1)*P]!=d2[i*P:(i+1)*P)][:5], "…")
EOF

# zboot 头 + zstd 帧参数（payload 大小 / 128MB 窗口）
# @0x480F600: magic "zimg"@+4, payload_offset@+8, payload_size@+12; zstd FHD 的 windowDescriptor 解码

# Kconfig 合法性（不改真 .config）
cp .config /tmp/kc_val && make -s KCONFIG_CONFIG=/tmp/kc_val olddefconfig && diff .config /tmp/kc_val | head
```

---

## 6. 一句话交付

**panel2 的内核不是"被新驱动搞死的"：那份驱动在 dtb 里被 `status="disabled"` 挡在门外，一次都没执行；panel2 唯一的实质变化是内核从 10.87MB 档跳到 14.76MB 档（解压后 45.7MB），而 14.76MB 档至今没有任何一次被证实能启动。** 先做"v35 内核 + 尾部 padding 撑到 14,868,992 B"这个单变量实验，或者把 ESP 改成 4KB 簇，5 分钟就能把"文件大小/簇数"和"驱动"彻底分开。
