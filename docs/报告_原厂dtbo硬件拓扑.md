# 魅族 21 Note (m2468 / SM8550 Kalama) 原厂 DTBO 逆向 —— I2C / QUP / GENI 硬件拓扑报告

生成时间：2026-10-28
数据来源：**全部来自原厂镜像**（`原厂镜像_回滚用\boot.img` / `vendor_boot.img` / `dtbo.img`，Flyme 12.6 / Android 13），
外加本机运行时 DT 转储 `live.dts`（board-id `0x03 0x05` = M2468 MP）做交叉验证。
工具：`dtc 1.7.x`、`fdtoverlay`、自写 FDT 解析器（`/tmp` 脚本，逻辑见第 9 节）。

> **本报告中每一个数字都是从 DTB 二进制里解析出来的**。凡未能证实的，第 7 节单独列"查不到"。

---

## 0. 结论速览（先看这个）

1. **m2468 上 QUP/GENI 的 MMIO 布局和 mainline `sm8550.dtsi` 完全一致**：3 个 QUP wrapper
   （`0xac0000` / `0x8c0000` / `0x9c0000`）+ 26 个 SE（24 个 I2C + 2 个 debug/hs UART）。**没有任何一处在主线树里"多出来"**。
   → 所以"照抄 m2381(nura) 的 dts 会点亮 m2468 上不存在的 I2C 控制器"这个假设，**在地址层面不成立**：
   坏的不是地址，是**总线被接到了别的外设上**，以及**属性/父节点上电**问题。
2. **`0x9c800000` 在原厂树里根本不存在**（也不在 mainline、不在 live DT、不在本机任何一份已构建 dtb 里）。
   它落在原厂 `reserved-memory` 的 `cvp_region@9c200000`（`0x9c200000+0x700000`，`no-map`，XPU/TZ 保护）内部
   —— 若该地址真的进了 DT，`ioremap` 后第一次 `readl` 必然 `synchronous external abort`。
   但同一段日志里还出现 `i2c@9880000`（多一个 0）、`typec-retimer@lc`，说明**日志是照片转录**，
   真实地址很可能是 `0x988000`（hub_i2c2）。两种情况都给出判据与修法（§2.6、§5、§6）。
3. 原厂**真正启用**的 QUP 通道共 7 条（3 个 wrapper 全开）：
   | 总线 | 地址 | 功能 | 挂的设备 |
   |---|---|---|---|
   | se0 I2C | `0xa80000` | NFC | `nq@27` (qcom,sn-nci) + `tms_thn31@28` (tms,nfc) |
   | **se4 SPI** | `0xa90000` | **触摸屏（SPI，不是 I2C！）** | `goodix-berlin@0` (goodix,brl-d) |
   | **se10 SPI** | `0x888000` | **UWB** | `sr100@0` (nxp,sr100) |
   | se15 I2C | `0x89c000` | 副 PMIC + 指示灯 | `pm8008i@8`/`@9` (qcom,i2c-pmic)、`aw2016@64` (awinic,aw2016_led) |
   | hub_i2c2 I2C | `0x988000` | Type-C/音频（子节点多为 disabled 桩） | `cs35l43@40/@41`、`fsa4480@42`、`nq@64` 全是 `disabled` |
   | se14 UART | `0x898000` | 蓝牙 HS-UART | — |
   | se7 UART | `0xa9c000` | 调试串口（`stdout-path`） | — |
4. **m2381(nura) 里 3 条 I2C 在 m2468 上是"同一寄存器块、不同协议/不同外设"**，照抄会争用同一 SE：
   `0xa90000`（nura=I2C 触摸 / m2468=SPI 触摸）、`0x888000`（nura=I2C cs35l45 / m2468=SPI UWB sr100）、
   `0x98c000`（nura=pm8008 / m2468 的 pm8008 在 **0x89c000**）。
   另有 `0x994000`（nura=aw8697 马达）在 m2468 上**原厂未启用**——m2468 的震动是 PM8550B（SPMI 从地址 7）里的 `qcom,hv-haptics@f000`（`okay`，reg `<0xf000 0xf100 0xf200>`），不是 I2C 马达。
5. 修复要点（详见 §6.2）：**删掉所有 `reg = <0x9c800000 ...>` 之类的手写 SE 节点**；SE 地址只能取第 2 节表格；
   三个 wrapper 必须 `status = "okay"`（父不活 → 子 SE 访问寄存器同样会 abort）；
   I2C 只开 `i2c0 / i2c15 / i2c_hub_2`，SPI 只开 `spi4 / spi10`，串口 `uart7`。

---

## 1. 原厂 `dtbo.img` 完整结构

### 1.1 Android DTBO header（实测字段）

`原厂镜像_回滚用\dtbo.img` = 2,097,152 B（正好 2 MiB 分区）。前 32 字节为 `struct dt_table_header`（大端）：

| 字段 | 值 | 说明 |
|---|---|---|
| `magic` | `0xd7b7ab1e` | DTBO 表魔数 ✔ |
| `total_size` | `1,964,830` | 全部 entry 数据结束位置（不是分区大小） |
| `header_size` | `32` | |
| `dt_entry_size` | `32` | |
| `dt_entry_count` | `5` | **5 个 overlay** |
| `dt_entries_offset` | `32` | entry 数组紧接 header |
| `page_size` | `4096` | |
| `version` | `0` | legacy（无 `dt_table_header_v1` 的 id/rev 匹配语义） |

`dtbo_b.img`（从设备 `dtbo_b` 分区整块 dump，25,165,824 B = 24 MiB）**header 与 5 个 entry 内容与 A 槽逐字节相同**
（`total_size` 同样是 1,964,830），差异只在分区容量/尾部填充。→ 谈"原厂 dtbo 内容"时 A/B 槽等价。

### 1.2 5 个 entry（overlay）明细

entry 结构 `struct dt_table_entry`：`dt_size(u32) dt_offset(u32) id(u32) rev(u32) custom[16]`（`custom` = 128B 名字）。

| # | dt_size | dt_offset | `id` | `rev` | `custom`(name) | 根 `meizu,board-id` | `meizu,chip-version` | fragment 数 | 作用 |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 392,430 | 192 | `0x00000000` | `0x00000000` | 空 | `<0x03 0x01>` | `M2468 B1` | 798 | 试产 B1 硬件配置 overlay |
| 1 | 391,465 | 392,622 | `0x00000000` | `0x00000000` | 空 | `<0x03 0x02>` | `M2468 B1.1` | 801 | +IR（`ir_active`/`ir_sleep`/`ir_pwm`）+ `aw2016@64` |
| 2 | 393,653 | 784,087 | `0x00000000` | `0x00000000` | 空 | `<0x03 0x03>` | `M2468 B2` | 804 | B2 配置 |
| 3 | 396,016 | 1,177,740 | `0x00000000` | `0x00000000` | 空 | `<0x03 0x04>` | `M2468 B2.1` | 812 | B2.1 配置（条目最多） |
| 4 | 391,074 | 1,573,756 | `0x00000000` | `0x00000000` | 空 | `<0x03 0x05>` | **`M2468 MP`** | 791 | **量产机（本机就是这一份）** |

要点：

* **5 个 entry 的 `id` 全为 0、名字全空**。说明本机 bootloader **不做 name/id 匹配**，而是按
  `androidboot.dtbo_idx=<n>`（bootconfig / cmdline）**按下标选择**。idx=4 即 MP 版。
* 每个 entry 都带 `qcom,msm-id = <0x218 0x20000 0x207 0x20000 0x207 0x10000 0x218 0x10000>`
  （kalama v2 / kalama v1 各两档）与 `qcom,board-id = <0x10008 0x00>`，`model = "Meizu M2468(kalama MTP) meizu,board-id = <0x3 0xN>"`。
* **本机实测**：运行时 DT 转储 `live.dts` 的根节点是 `meizu,board-id = <0x03 0x05>`、`meizu,chip-version = "M2468 MP"`
  → 确认本机 = entry 4（MP）。第 3、4 节的状态表因此以 entry 4 为准。

### 1.3 overlay 的组织方式（重要）

每个 entry **不是**一棵完整设备树，而是 **798~812 个 `fragment@N`**：

```dts
fragment@0 {
    target = <0xffffffff>;        /* 占位符，dtbo 里不可解析 */
    __overlay__ { ... };
};
```

`target` 的 `0xffffffff` 由 `__fixups__` 段里的**标签名**决定。从原厂 dtbo 的 fixup 表（86 个不同目标标签）可以看到
overlay 到底往哪些节点上贴东西：

```
spmi_bus, thermal_zones, soc, tlmm, gcc, ufsphy_mem, ufshc_mem, L9B, L12B, L16B,
sdhc_2, usb0, ucsi, battery_charger, pcie1, disp_rsc_drv0,
cam_cci0, cam_cci1,
qupv3_se0_i2c, qupv3_se4_spi, qupv3_se10_spi, qupv3_se15_i2c, qupv3_hub_i2c2,
qupv3_se7_2uart, qupv3_se4_spi_sleep, qupv3_se10_spi_cs_active/sleep,
fsa4480, lpass_cdc, lpi_tlmm, spf_core_platform, reserved_memory, system_cma,
qseecom_mem/qseecom_ta_mem, mpss_mem/mpss_dsm_mem, spss_utils, qcom_tzlog ...
```

→ **外设（NFC/触摸/UWB/PM8008/功放/马达）全部来自 overlay，不是 base DTB**。这也解释了为什么前面用
`grep i2c@` 在单个 entry 的 dts 文本里搜不到 `i2c@`：overlay 里是"往 `<&qupv3_se4_spi>` 里塞子节点"，不重复写 SE 节点名。

### 1.4 base DTB 在哪，以及 base 与合成结果的差异（这是最关键的证据）

| 文件 | 大小 | 内容 |
|---|---|---|
| `vendor_boot.img` 里的 `base_vb_0.dtb` | 518,252 B | **SoC 骨架**：`model = "Qualcomm Technologies, Inc. Kalama v2 SoC"`，`compatible = "qcom,kalama"`，`qcom,board-id=<0 0>`，根下只有 `soc`（注意节点名是 `/soc`，不是 `/soc@0`）、`memory`、`chosen`、`reserved-memory`、`aliases`、`cpus`… |
| `dtbo.img` 5 个 entry | 391~396 KB | 板级 overlay（见 1.2） |
| `merged_full.dtb`（base + entry 合成） | 860,880 B | `/soc` 下 500+ 节点，即"开机时内核真正看到的树" |
| `live.dts`（设备运行时转储） | — | 与 merged 一致（逐条状态核对过，见第 8 节附件） |

**base 与 merged 的 QUP 差异（证明哪条总线是「板子决定要开」的）**：

| 总线 | 仅在 base_vb_0 中 | base+dtbo 合成后 |
|---|---|---|
| `qcom,qup_uart@a9c000`（console） | `ok` | `ok` |
| `i2c@988000`（hub_2） | `ok` | `ok` |
| `i2c@a80000`（NFC） | `disabled` | **`ok`** ← overlay 打开 |
| `spi@a90000`（触摸） | `disabled` | **`ok`** ← overlay 打开 |
| `spi@888000`（UWB） | `disabled` | **`ok`** ← overlay 打开 |
| `i2c@89c000`（PM8008） | `disabled` | **`ok`** ← overlay 打开 |

---

## 2. m2468 真实存在的全部 I2C / SPI / QUP 控制器总表

原厂 SE 编号（`aliases` 实测）与 mainline 编号**完全对齐**：
`qupv3_se0..se6 → 0xa80000/a84000/a88000/a8c000/a90000/a94000/a98000`，
`qupv3_se7_2uart → 0xa9c000`，
`qupv3_se8..se13 → 0x880000/884000/888000/88c000/890000/894000`，
`qupv3_se14_4uart → 0x898000`，`qupv3_se15 → 0x89c000`，
`qupv3_hub_i2c0..9 → 0x980000/984000/988000/98c000/990000/994000/998000/99c000/9a0000/9a4000`。

### 2.1 三个 QUP wrapper（GENI-SE 控制器组）

| 节点 | reg | compatible | status | clocks（clock-names） | iommus | 备注 |
|---|---|---|---|---|---|---|
| `/soc/qcom,qupv3_1_geni_se@ac0000` | `0xac0000+0x2000` | `qcom,geni-se-qup` | `ok` | 2 路：`m-ahb`,`s-ahb`（`<&gcc 0x7f>`,`<&gcc 0x80>`） | `<&apps_smmu 0xa3 0>` | 挂 se0~se7 |
| `/soc/qcom,qupv3_2_geni_se@8c0000` | `0x8c0000+0x2000` | `qcom,geni-se-qup` | `ok` | 2 路：`m-ahb`,`s-ahb`（`0x81`,`0x82`） | `<&apps_smmu 0x423 0>` | 挂 se8~se15 |
| `/soc/qcom,qupv3_i2c_geni_se@9c0000` | `0x9c0000+0x2000` | `qcom,geni-se-qup` | `ok` | 2 路：`m-ahb`,`s-ahb`（都是 `0x5a`） | **无 iommus** | 挂 hub_i2c0~9；三个 wrapper 都有 `ranges;` `dma-coherent`(前两个) |

> 注意：`0x9c0000` **不是** I2C SE，是"QUP for I2C hub"的 wrapper。任何把它当 SE 用（或把它的 ID 写错量级）的 DT 都会炸。

### 2.2 QUPv3_1 @0xac0000（se0~se7）

| SE | 节点名 | reg | compatible | status | I2C 时钟 | 子设备 |
|---|---|---|---|---|---|---|
| se0 | `i2c@a80000` | `0xa80000+0x4000` | `qcom,i2c-geni` | **ok** | `se-clk`×1 | `nq@27`(qcom,sn-nci,ok)、`tms_thn31@28`(tms,nfc,ok) |
| se0' | `i3c-master@a80000` | `0xa80000+0x4000` + `0xec90000+0x10000` | `qcom,geni-i3c` | disabled | | — |
| se0'' | `spi@a80000` | `0xa80000+0x4000` | `qcom,spi-geni` | disabled | | — |
| se1 | `i2c@a84000` | `0xa84000` | `qcom,i2c-geni` | disabled | | — |
| se2 | `i2c@a88000` | `0xa88000` | `qcom,i2c-geni` | disabled | | — |
| se3 | `i2c@a8c000` | `0xa8c000` | `qcom,i2c-geni` | disabled | | — |
| se4 | `i2c@a90000` | `0xa90000` | `qcom,i2c-geni` | disabled | | — |
| **se4** | **`spi@a90000`** | `0xa90000` | `qcom,spi-geni` | **ok** | | **`goodix-berlin@0`(goodix,brl-d)**：reset gpio24 / irq gpio25 |
| se4' | `uart@a90000` | `0xa90000` | `qcom,msm-geni-serial-hs` | disabled | | — |
| se5 | `i2c@a94000` | `0xa94000` | `qcom,i2c-geni` | disabled | | — |
| se6 | `i2c@a98000` | `0xa98000` | `qcom,i2c-geni` | disabled | | — |
| **se7** | **`qcom,qup_uart@a9c000`** | `0xa9c000` | `qcom,geni-debug-uart` | **ok** | | `chosen/stdout-path` 指这里 |

### 2.3 QUPv3_2 @0x8c0000（se8~se15）

| SE | 节点名 | reg | status | 子设备 |
|---|---|---|---|---|
| se8 | `i2c@880000` / `spi@880000` / `i3c-master@880000` | `0x880000` | 全 disabled | — |
| se9 | `i2c@884000` / `spi@884000` / `i3c-master@884000` | `0x884000` | 全 disabled | — |
| se10 | `i2c@888000` | `0x888000` | disabled | — |
| **se10** | **`spi@888000`** | `0x888000` | **ok** | **`sr100@0`(nxp,sr100) UWB**：ri=gpio70、ce=gpio170、ldo-en=gpio73 |
| se11 | `i2c@88c000` / `spi@88c000` | `0x88c000` | disabled | — |
| se12 | `i2c@890000` / `spi@890000` | `0x890000` | disabled | — |
| se13 | `i2c@894000` / `spi@894000` | `0x894000` | disabled | — |
| se14 | **`qcom,qup_uart@898000`** | `0x898000` | **ok** | 蓝牙 HS-UART（`aliases/hsuart0`） |
| **se15** | **`i2c@89c000`** | `0x89c000` | **ok** | `pm8008i@8`(qcom,i2c-pmic，含 `pm8008-chip@900`)、`pm8008i@9`（7 个 regulator@4000~4600）、`aw2016@64`(awinic,aw2016_led) |
| se15' | `spi@89c000` | `0x89c000` | disabled | — |

### 2.4 QUP for I2C hub @0x9c0000（hub_i2c0~9）

10 个 SE，**全部 `compatible = "qcom,i2c-geni"`，都带两路时钟 `se-clk` + `core-clk`**（与 QUP1/2 的单 `se-clk` 不同），
interconnect 只有 `qup-core`,`qup-config`（无 `qup-memory`），无 `dmas`：

| SE | reg | status | 子设备 |
|---|---|---|---|
| hub_i2c0 | `0x980000` | disabled | — |
| hub_i2c1 | `0x984000` | disabled | — |
| **hub_i2c2** | **`0x988000`** | **ok** | `cs35l43@40`(cirrus,cs35l43,disabled)、`cs35l43@41`(disabled)、`fsa4480@42`(qcom,fsa4480-i2c,**disabled**)、`nq@64`(rtc6226,`disable`) |
| hub_i2c3 | `0x98c000` | disabled | — |
| hub_i2c4 | `0x990000` | disabled | — |
| hub_i2c5 | `0x994000` | disabled | — |
| hub_i2c6 | `0x998000` | disabled | — |
| hub_i2c7 | `0x99c000` | disabled | — |
| hub_i2c8 | `0x9a0000` | disabled | — |
| hub_i2c9 | `0x9a4000` | disabled | — |

> 也就是说：**m2468 上一个 I2C 马达/音频功放都不在 hub 上**。hub_i2c2 虽 `ok`，但 4 个子节点全 disabled（功放实际走 SoundWire `swr0` 的 WSA8845，见 `&swr0` 的 `speaker@0,0`/`@0,1`）。

### 2.5 相机 I2C（CCI，独立于 QUP）

| 节点 | reg | compatible | status | 子设备 |
|---|---|---|---|---|
| `/soc/qcom,cci0@ac15000` | `0xac15000` | `qcom,cci,simple-bus` | **ok** | `qcom,cam-sensor0`、`qcom,cam-sensor2`、`qcom,actuator0/2`、`qcom,ois0`、`qcom,eeprom0/2` |
| `/soc/qcom,cci1@ac16000` | `0xac16000` | 同上 | **ok** | `qcom,cam-sensor1`、`qcom,eeprom1` |
| `/soc/qcom,cci2@ac17000` | `0xac17000` | 同上 | **ok** | （无传感器，仅模式表） |

### 2.6 ★ `0x9c800000` 专项查证

| 检查项 | 结果 |
|---|---|
| 原厂 merged 树（base+dtbo，`/soc` 500+ 节点）有没有 `reg` 落在 `0x9c800000`？ | **没有**。`grep "9c8000"` 全树 0 命中 |
| 节点名 `i2c@9c800000` 是否存在？ | **不存在**。对 `merged_full.dtb` / `live.dtb` / `sm8550-meizu-21note.dtb` / 5 个 entry dtb 做 `strings \| grep 9c800000` → **全部 0 命中**（DTB 里节点名是明文字符串，存在必然命中） |
| mainline `sm8550*.dtsi` 有没有？ | **没有**（全 `arch/arm64/boot/dts/qcom/` grep `9c80` → 0 命中） |
| 那 `0x9c800000` 是什么？ | 原厂 `reserved-memory` 里 `cvp_region@9c200000`（`0x9c200000 + 0x700000`，即 `0x9c200000–0x9c900000`，`no-map`）→ `0x9c800000` 在该区间内，是 **CVP（视觉固件）的 XPU 保护保留区** |
| 真正常见被写错的目标 | `0x9c0000` = `qcom,qupv3_i2c_geni_se@9c0000`（wrapper，`ok`）；hub SE 是 `0x980000~0x9a4000`。**`0x9c8000` 这个地址同样不存在**（没有任何 SE 在 `0x9c8xxx`） |

结论：`geni_i2c 9c800000.i2c` **不可能来自原厂 DT**。它有两种解释，第 6 节给出判别实验：

* **假设甲（地址写坏）**：崩溃那次用的 DTB 里该 SE 的 `reg` 被写成 `0x9c800000`（典型手改/AI 改 dts 时
  `0x00988000` → `0x009c80000`/`0x9c800000` 这类串损坏）。落到 `no-map`+XPU 保护的 CVP 保留区里，
  `geni_se_resources_on()` 之后的**第一次 `readl` 就 external abort** —— 与 `geni_i2c_probe+0x390` 吻合。
* **假设乙（日志转录噪声）**：设备名由 `of_device_make_bus_id()`（`"%llx.%pOFn"`）用 `of_translate_address()`
  译出的 `reg` 拼成，理论上不会"打印错"；但这份日志是**屏幕照片转写**的——同一段里还出现 `i2c@9880000`
  （多一个 0）、`typec-retimer@lc`（`1c` 被读成 `lc`）。若 `9c800000` 也是转录噪声，则真实地址是
  **`0x988000`（hub_i2c2，原厂唯一启用的 hub SE）**，此时根因退回到"时钟/电源域/icc 没真正打开"（见第 5 节 2、3 条）。
  注：本目录另有 `报告_geni_i2c崩溃根因.md`、`报告_差异对比与可行路径.md` 两份同期分析，同样判定 `0x9c800000`
  在 nura/我方/原厂/live 四套 DTS 里全都不存在，并倾向"日志噪声"。


---

## 3. 与原厂"同址不同功能"的确认：m2381(nura) vs m2468

mainline `sm8550.dtsi` 的 26 个 SE 地址与 m2468 **逐一对应，一个不多一个不少**：

```
qupv3_id_0 geniqup@ac0000 → i2c0..i2c6 (a80000,a84000,a88000,a8c000,a90000,a94000,a98000) + uart7(a9c000)
qupv3_id_1 geniqup@8c0000 → i2c8..i2c13 (880000,884000,888000,88c000,890000,894000) + serial@898000 + i2c15(89c000)
i2c_master_hub_0 geniqup@9c0000 → i2c_hub_0..9 (980000..9a4000)
```

→ **"m2381 有但 m2468 没有的 I2C 控制器"= 空集**（地址层面）。真正的问题是**同一条总线在两张板子上接的外设不同**，
以及 nura 的 dts 打开了 m2468 上未使用/已改作他途的 SE：

| reg | nura(m2381) 用它做什么 | m2468 实际用它做什么 | 冲突性质 |
|---|---|---|---|
| `0xa90000` (se4) | `&i2c4`：`touchscreen@5d` goodix,gt9916（I2C） | **`spi@a90000` + `goodix-berlin@0`（SPI）** | **协议冲突，同一 SE 不能既 I2C 又 SPI**。照抄 nura 的 `&i2c4` 会与 m2468 的触摸抢同一个块/引脚 |
| `0x888000` (se10) | `&i2c10`：`cs35l45@30`（音频功放，I2C） | **`spi@888000` + `sr100@0`（UWB，SPI）** | **协议冲突**；m2468 功放在 SoundWire，不在 QUP |
| `0x98c000` (hub_3) | `&i2c_hub_3`：`pm8008@8` | **disabled**；m2468 的 PM8008 在 **`0x89c000`(se15)** | 外设搬家：照抄会得到一条空总线（不崩，但 PM8008 拿不到） |
| `0x994000` (hub_5) | `&i2c_hub_5`：`haptics@5a` aw8697 | **disabled**；m2468 震动 = PM8550B 内 `qcom,hv-haptics@f000`（SPMI @7，okay） | 外设不存在 → 照抄只会 probe 到空总线 |
| `0xa80000` (se0) | `nfc@28` nxp,nxp-nci-i2c | `nq@27` qcom,sn-nci + `tms_thn31@28` | 同一总线，**NFC 从机地址不同（0x28 vs 0x27）** |
| `0x89c000` (se15) | **disabled** | **`ok`**：pm8008i@8/@9 + aw2016@64 | m2468 独有，nura 没有 |
| `0x988000` (hub_2) | `&i2c_hub_2`：nb7vpq904m@1c 等 | `ok` 但子节点全 disabled | 都是"启用但外设不同" |
| `0x898000` (se14) | `serial@898000` ok | `ok` 蓝牙 | 一致 |
| `0xa9c000` (se7) | `serial@a9c000` ok | `ok` console | 一致 |

我方当前 `sm8550-meizu-21note.dts`（编译产物 `sm8550-meizu-21note.dtb` 实测）只开了：
`&qupv3_id_0{ok}`、`&i2c_master_hub_0{ok}`、`&i2c_hub_2{ok}`（= `0x988000`）、`&qupv3_id_1` **未开**。
→ 从这份 dts 出发**根本不会有 `geni_i2c` 在 `0x9c800000` 上 probe**，"9c800000" 必定来自另一份被写坏的 dts
（例如照 nura 改过、或手工加过 SE 节点的那一版）。

---

## 4. 属性对比：原厂 vs mainline（供电/时钟/pinctrl/icc）

### 4.1 wrapper

| 属性 | 原厂 m2468 | mainline `sm8550.dtsi` | 影响 |
|---|---|---|---|
| `reg` | `0xac0000+0x2000` 等 | 同 | ✔ |
| `clocks/clock-names` | `m-ahb`,`s-ahb`（`0x9c0000` 那路两个 ID 相同=同一 S_AHB 时钟） | `qupv3_id_0/1`：`m-ahb`,`s-ahb`；**`i2c_master_hub_0`：只有 `s-ahb`（1 路）** | 主线 hub wrapper 少一路 m-ahb，实测可工作（6.14 已是此写法） |
| `iommus` | `0xa3`(QUP1) / `0x423`(QUP2) / hub 无 | `0xa3` / `0x423`（hub 无） | ✔ 一致 |
| `dma-coherent`、`ranges` | 有 | 有 | ✔ |
| `status` | `ok` | `disabled`（默认）→ **必须显式 `okay`** | ⚠ 父不活 → 子 SE 的 AHB 时钟永不使能 → 访问 SE 寄存器 external abort |

### 4.2 I2C SE（以 `0xa80000` / `0x89c000` / `0x988000` 为例）

| 属性 | 原厂 QUP1/2 SE | 原厂 hub SE | mainline SE | 备注 |
|---|---|---|---|---|
| `compatible` | `qcom,i2c-geni` | `qcom,i2c-geni` + `qcom,i2c-hub`(空属性标记) | `qcom,geni-i2c`；hub 用 `qcom,geni-i2c-master-hub` | **字符串完全不同**，不能混用（下游驱动 vs 主线驱动） |
| `reg` | `0xNNNNNN+0x4000` | 同 | 同 | ✔ |
| `clock-names` | `se-clk` | `se-clk`,`core-clk` | `se`（hub：`se`,`core`） | **名字不同**：主线要 `se`/`core`，写 `se-clk` 会 `devm_clk_get` 失败 |
| `clocks` | 1 路（hub 2 路） | | 1 路（hub 2 路，hub 的 core 是共享 `GCC_QUPV3_I2C_CORE_CLK`） | 一致 |
| `interconnects` | `qup-core`,`qup-config`,`qup-memory` 3 条 | `qup-core`,`qup-config` 2 条 | 同（3 条 / 2 条） | 一致，**缺 icc 会导致寄存器访问 abort** |
| `power-domains` | **无**（下游自己管） | 无 | `<&rpmhpd RPMHPD_CX>` + `required-opps`/`operating-points-v2 = <&qup_opp_table_120mhz>` | 主线独有；不能删 |
| `pinctrl-*` | `default`,`sleep`（`pinctrl-0` 2 个 phandle，`pinctrl-1` 1 个） | 同 | `default`(+`sleep`) | 主线默认只 `default`；接外设时按需加 |
| `dmas/dma-names` | QUP1/2 有（gpi_dma）；hub 无 | 无 | QUP1/2 有；hub 无 | 一致 |
| `interrupts` | `<0 0x161 4>`（GIC SPI 353）等 | `<0 0x1d2 4>` | 同编号 | ✔ 完全一致（可用来校验地址对不对） |
| `qcom,clk-freq-out` | `0x61a80`=400 kHz | 同 | 主线用 `clock-frequency` | ⚠ **panic 里的 "Bus frequency not specified" 就是没写 `clock-frequency`** |
| `qcom,i2c-hub` | hub SE 有 | — | 无（用 compatible 区分） | — |

**中断号是最硬的指纹**：原厂 `i2c@a80000` = GIC SPI 353、`i2c@89c000` = 462、`i2c@988000` = 466，
与 mainline `i2c0`/`i2c15`/`i2c_hub_2` 的 `interrupts` 逐一相同 → 再次证明地址表没错。

---

## 5. 崩溃机制（从 6.14.11 驱动源码推演，不用猜）

`drivers/i2c/busses/i2c-qcom-geni.c: geni_i2c_probe()` 顺序：

```c
gi2c->se.base = devm_platform_ioremap_resource(pdev, 0);      // ioremap，不访问寄存器
desc = device_get_match_data(...);                            // master-hub 时 has_core_clk
if (desc->has_core_clk) core_clk = devm_clk_get(dev, "core");
gi2c->se.clk = devm_clk_get(dev, "se");
device_property_read_u32(dev, "clock-frequency", &clk_freq_out);
  ↳ 失败时打印 "Bus frequency not specified, default to 100kHz."   ← 日志里那句
gi2c->irq = platform_get_irq(...); devm_request_irq(...);
geni_icc_get(); geni_icc_set_bw();                            // qup-core/qup-config/qup-memory
clk_prepare_enable(core_clk);
geni_se_resources_on(&gi2c->se);                              // pinctrl + se clk + icc
proto = geni_se_read_proto(&gi2c->se);                        // ★ 第一次 readl(SE_GENI_S_GENI_STATUS)
```

`geni_se_read_proto()` 是**第一次真正读 SE 寄存器**，位置正好落在 `probe+0x390` 这一档。
所以 abort 只有三种可能，全部与 DT 有关：

1. **`reg` 地址不是 MMIO**（本例：若 `0x9c800000` 为真，它落在 CVP `no-map` 保留区）→ 必然 abort。
2. **父 wrapper `status="disabled"`**：`se.wrapper` 为 NULL，`m-ahb/s-ahb` 永不使能 → 访问 SE 也可能 abort/挂死。
3. **SE 缺 `interconnects` / `power-domains`**：NoC 从口未开，访问即 external abort（这正是"照抄下游属性到主线"最容易漏的两项）。

`0x96000010` 是 ESR：`EC=0x25`（同 EL 的 data abort）+ `IFSC=0x10`（synchronous external abort），
即"读了一个不允许/未映射的物理地址"。第 1 条与第 3 条都会产生这个 ESR，所以**光看 ESR 无法区分**，
必须靠原始 dmesg 里的 unit address 或逐项 A/B（§6.3）。

---

## 6. 结论 + 可直接抄的 DT 改法

### 6.1 结论

* 原厂 m2468 的 QUP 拓扑 = mainline `sm8550.dtsi` 的拓扑（3 wrapper + 26 SE，地址/中断/时钟名逐项对得上）。
  **不存在"m2381 有、m2468 物理没有"的 I2C 控制器**。会让内核 abort 的只有四类，按可能性排序：
  1. **`reg` 不是有效 MMIO**（`0x9c800000` 这种；本机若日志数字为真即此条）；
  2. **父 wrapper `status` 不是 okay** → SE 的 AHB 时钟永不使能；
  3. **SE 缺 `interconnects` / `power-domains`**（从下游 dts 抄属性最容易漏）；
  4. **`clock-names` 写错**（下游 `se-clk`/`core-clk` vs 主线 `se`/`core`）→ 直接 defer，不 abort 但起不来。
* 若日志的 `9c800000` 是转录噪声（真实为 `0x988000` = hub_i2c2），则主因是 2/3/4 而不是地址——
  所以 **先修 pstore 拿原始 dmesg**，再决定改地址还是补属性，别盲改。
* `0x9c0000` 是 **wrapper** 不是 I2C SE，不能当 i2c 设备节点用；`0x9c8000` 也不存在（没有任何 SE 在 `0x9c8xxx`）。

### 6.2 建议的 dts 片段（直接抄进 `sm8550-meizu-21note.dts`）

```dts
/* ---------- 1) 三个 QUP wrapper 必须全部打开（父不活，子 SE 必炸） ---------- */
&qupv3_id_0        { status = "okay"; };   /* 0xac0000  se0..se7  */
&qupv3_id_1        { status = "okay"; };   /* 0x8c0000  se8..se15 */
&i2c_master_hub_0  { status = "okay"; };   /* 0x9c0000  hub_i2c0..9 */

/* ---------- 2) 只开原厂真正在用的 6 条总线，其它一律 disabled ---------- */
/* se0  I2C 0xa80000  NFC */
&i2c0 {
        status = "okay";
        clock-frequency = <400000>;
        /* m2468: qcom,sn-nci @0x27（原厂同址还有 tms_thn31@28 模板，二选一） */
        nfc: nfc@27 {
                compatible = "qcom,sn-nci";
                reg = <0x27>;
                interrupt-parent = <&tlmm>;
                interrupts = <55 IRQ_TYPE_LEVEL_HIGH>;   /* 原厂 irq = 0x37 = 55 */
                enable-gpios  = <&tlmm 30 GPIO_ACTIVE_HIGH>;
                firmware-gpios = <&tlmm 85 GPIO_ACTIVE_HIGH>;
        };
};

/* se4  SPI 0xa90000  触摸（m2468 是 SPI，不是 I2C！别用 &i2c4） */
&spi4 {
        status = "okay";
        pinctrl-names = "default", "sleep";
        /* 原厂 spi@a90000: pinctrl-0 = 4 个 phandle（miso/mosi/clk/cs），pinctrl-1 = 1 个 sleep
         * 对应 /soc/pinctrl@f000000/qupv3_se4_spi_pins 下的 4 个 active 子节点，照抄 gpio/function 即可 */
        touchscreen@0 {
                compatible = "goodix,brl-d";
                reg = <0>;
                interrupt-parent = <&tlmm>;
                interrupts = <25 IRQ_TYPE_EDGE_FALLING>;  /* 原厂 irq 0x19=25 */
                reset-gpios = <&tlmm 24 GPIO_ACTIVE_LOW>; /* 原厂 reset 0x18=24 */
                spi-max-frequency = <10000000>;
        };
};

/* se10 SPI 0x888000  UWB */
&spi10 {
        status = "okay";
        uwb@0 {
                compatible = "nxp,sr100";
                reg = <0>;
                interrupt-parent = <&tlmm>;
                interrupts = <176 IRQ_TYPE_LEVEL_HIGH>;      /* 原厂 interrupts=<0xb0 0> = gpio176 */
                enable-gpios = <&tlmm 170 GPIO_ACTIVE_HIGH>; /* ce  = gpio170 (0xaa) */
                /* 其余原厂私有属性：ri=gpio70(0x46)、ldo-en=gpio73(0x49)、rfclk-req=gpio200(0xc8) */
                clocks = <&rpmhcc RPMH_RF_CLK2>;             /* 原厂 clocks=<&... 0x1d> + sleep_clk */
                clock-names = "uwb_refclk", "sleep_clk";
        };
};

/* se15 I2C 0x89c000  副 PMIC(PM8008) + aw2016 指示灯 —— m2381 上这条是关的 */
&i2c15 {
        status = "okay";
        clock-frequency = <400000>;
        /* pm8008@8 / pm8008@9 + aw2016@64，驱动侧按 qcom,pm8008 / awinic,aw2016 填 */
};

/* hub_i2c2 I2C 0x988000  Type-C 开关/功放（原厂子节点全 disabled，可按需开 fsa4480） */
&i2c_hub_2 {
        status = "okay";
        clock-frequency = <400000>;
};

/* se7 UART 0xa9c000 调试串口（console），保持 okay */
&uart7 { status = "okay"; };

/* ---------- 3) 明确不要做这些事 ---------- */
/* ✗ 不要写任何 reg = <0x9c800000 ...> —— 该地址是 CVP no-map 保留区，读一下必 external abort */
/* ✗ 不要把 0x9c0000 当 I2C SE 用 —— 它是 qcom,geni-se-qup wrapper */
/* ✗ 不要照抄 nura 的 &i2c4 (0xa90000) / &i2c10 (0x888000) / &i2c_hub_3 (0x98c000) / &i2c_hub_5 (0x994000) */
/*    → m2468 上前两条被 SPI 触摸/UWB 占用，后两条原厂未使用 */
```

### 6.3 验证顺序（建议）

0. **先修 pstore/ramoops，拿原始 dmesg**，确认 `geni_i2c <addr>.i2c` 的真实 unit address（决定是改地址还是补属性）。
1. 只开 3 个 wrapper，不加任何 SE → 开机应无 `geni_i2c` 任何 probe（确认 wrapper 不炸）。
2. 加 `&i2c0`（NFC，最简单、原厂 `qcom,sn-nci` 有主线驱动 `nxp-nci_i2c` 可换）→ 看 `i2cdetect -y 0` 是否见 0x27。
3. 再加 `&i2c15`（PM8008）→ 能读到 0x8/0x9。
4. 最后才碰 SPI 触摸（`&spi4`），它依赖 panel/电源，容易误判成 I2C 问题。

---

## 7. 明确"查不到 / 未证实"的部分

1. **`geni_i2c 9c800000.i2c` 具体出自哪一份 dts**：本机上所有已构建 dtb（`sm8550-meizu-21note.dtb`、nura.dtb、
   merged/live）都没有这个节点，所以无法定位到具体源文件；只能确定"不是原厂、不是当前这份 21note dts"。
   另一个可能是该数字本身是屏幕照片的转录噪声（见 §2.6 假设乙）。
2. **m2468 的 5 个 dtbo entry 之间的实质差异**：只做了结构级 diff（B1 缺 IR 相关 fragment + `aw2016@64`），
   没有逐个 fragment 做语义级差异（804 vs 812 个 fragment 的具体内容）。若需要可以再做一次全量 fragment 级 diff。
3. **`spi@a90000`(触摸) / `spi@888000`(UWB) 的完整引脚配置**：原厂 `pinctrl-0` 只是 phandle，未反解到具体 gpio/function。
   要写主线 dts 的话，需要从 `pinctrl@f000000/qupv3_se4_spi_pins`、`qupv3_se10_spi_pins` 里逐个 mux/config 抄过来（原厂有，可查）。
4. **`0x9c800000` 是否一定被 XPU 保护**：能确认它在 `cvp_region`（`no-map`）区间内；XPU 具体策略表在 TZ 里，未反解。
   但"`no-map` 保留区内做设备访问 → external abort"已足够解释现象。
5. **hub_i2c2 上 `cs35l43` 为何 disabled**：原厂 MP entry 里功放走 `swr0`(WSA8845)，hub_i2c2 只剩 disabled 桩；
   m2468 是否还存在另一颗 I2C 功放，未在本树中看到。

---

## 8. 附件（同目录）

| 文件 | 内容 |
|---|---|
| `原厂m2468_QUP与I2C全量清单.csv` | 93 行：3 wrapper + 全部 SE + 全部子设备的 path/compatible/reg/status/clocks/pinctrl/interconnects/power-domains/dma |
| `qup_i2c_对照表.csv` | 29 行：按 reg 基址把 mainline 标签 / 原厂 base / 原厂合成 / live DT / nura / 我方 21note 的状态并排，含判定 |
| `属性差异_原厂vs主线.csv` | 6 个关键节点的逐属性对比（clocks/clock-names/icc/power-domains/iommus/...） |
| `差集_m2381mainline相对原厂m2468.txt` | 以 reg 为单位的启用集合差集 |
| `0x9c800000_查证.txt` | 该地址的四路查证过程与结论 |
| `原厂dtbo结构.txt` | dtbo header/entry 原始字段 + alias/SE 编号对照 |

## 9. 复现方法（脚本在 `/tmp` / WSL）

```bash
# 1) 拆 dtbo 表头
python3 - <<'EOF'   # struct.unpack('>8I', hdr[:32])
EOF
# 2) base DTB 从 vendor_boot 抽 → base_vb_0.dtb（518,252 B）
# 3) fdtoverlay -i base_vb_0.dtb -o merged_full.dtb entry_dtbo_*.dtb
# 4) 自写 FDT 解析器（fdtparse.py）：按 off_dt_struct 走 token
#    FDT_BEGIN_NODE(1)/END_NODE(2)/PROP(3)/NOP(4)/END(9)，
#    节点名与属性值都要 4 字节对齐（这一条写错会解析出乱树）
# 5) 用 FDT 解析器枚举 reg/compatible/status/clocks/pinctrl/icc，再与 sm8550.dtsi 对照
```
