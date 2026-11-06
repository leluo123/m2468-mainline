# 魅族 21 Note (m2468) / SM8550 mainline 6.14.11
# `geni_i2c_probe+0x390` synchronous external abort 根因报告

生成时间：2026-10-28
内核：`/home/shrp/linux-6.14.11`（ARCH=arm64，aarch64-linux-gnu-，vmlinux 有符号）
崩溃日志时间：2026-10-28 02:11（uptime 41.5~43.0 s）

---

## 0. 结论摘要（TL;DR）

1. **`+0x390` 精确对应**：`geni_i2c_probe()` 里 `geni_se_read_proto(&gi2c->se)` 对 **SE 寄存器块 +0x68（`GENI_FW_REVISION_RO`）的第一笔 32 位读**，即 `drivers/i2c/busses/i2c-qcom-geni.c:873` → `include/linux/soc/qcom/geni-se.h:328` 的 `readl_relaxed(se->base + GENI_FW_REVISION_RO)`。这是 probe 流程里**第一次真正访问该硬件块**（此前只做了 ioremap / 取时钟 / ICC 投票 / 上下电）。
2. **`synchronous external abort`（ESR 0x96000010，EC=0x25 DABT，DFSC=0x10，WnR=0 读）** 的含义是：**总线从设备没有应答**。对一笔 SE 寄存器读而言只有两种可能：
   - **(A) 地址不对**：`reg` 指向的物理地址在 SoC 中没有 GENI SE 从设备 → 译码失败 → external abort；
   - **(B) 该 SE 的时钟/电源域实际没开**（QUP S-AHB / SE clk / CX 域）→ 从设备不响应 → 同样 external abort。
3. **日志本身把 (A) 钉死了**，这是本次分析最关键的一条硬证据：
   `geni_i2c 9c800000.i2c` 里的 `9c800000` **不是 DTS 节点名，而是内核用 `of_translate_address(node, reg)` 算出来、再由 `of_device_make_bus_id()` 拼进设备名的地址**（源码：`drivers/of/device.c:288`，格式串 `"%llx.%pOFn"`）。
   也就是说：**崩溃那次启动所用 DTB 中，这个 i2c 节点的 `reg` 被内核翻译成了 `0x9c800000`，而真实的 SM8550 QUPV3_I2C(I2C master hub) SE#2 是 `0x988000`。**
   `0x9c800000`（约 2.6 GB 物理地址）不属于任何 QUPV3 SE 窗口（hub SE 窗口只有 `0x980000~0x9a7fff`，wrapper 配置在 `0x9c0000`），读它必然 external abort。
4. **同时发现一个工程级问题**：工作区里 `/home/shrp/_tmp/nura_build/m2468.dtb`（以及 Mu FdtBlob 里那份）**该节点是正确的**（`reg=<0x0 0x988000 0x0 0x4000>`、`clock-frequency=<400000>`、节点名 `i2c@988000`）。
   而崩溃日志有三条与之矛盾（缺 `clock-frequency`、节点名 `i2c@9880000`、reg 译成 `0x9c800000`）。
   **⇒ 02:11 那次启动加载的 DTB 不是这份 m2468.dtb。**必须先解决"到底启动的是哪一份 DT"，否则改 dts 全是空转（详见 §3.3、实验 E1）。
5. 该 I2C 控制器在**本机是真实存在的**（厂商 DT `/soc/qcom,qupv3_i2c_geni_se@9c0000/i2c@988000` 上挂着 cs35l43 智能功放 ×2 + fsa4480 Type-C mux），所以正确处理是**把 `reg`/属性补对**，不是删节点；`status="disabled"` 只能作为定位手段。

---

## 1. 崩溃点的源码级精确定位

### 1.1 取符号地址

```bash
$ wsl -e bash -lc 'cd /home/shrp/linux-6.14.11 && aarch64-linux-gnu-nm vmlinux | grep -w geni_i2c_probe'
ffff800080deb3ec t geni_i2c_probe
```

崩溃 `pc = geni_i2c_probe+0x390`：

```
0xffff800080deb3ec + 0x390 = 0xffff800080deb77c
lr  = +0x380             = 0xffff800080deb76c
```

### 1.2 反汇编（原始输出）

```bash
$ aarch64-linux-gnu-objdump -d --start-address=0xffff800080deb3ec \
      --stop-address=0xffff800080debaa0 vmlinux
```

关键片段（完整片段见 §7 脚本）：

```
ffff800080deb760:  35000e60   cbnz  w0, ...<geni_i2c_probe+0x540>   ; if (ret) goto err_clk
ffff800080deb764:  aa1303e0   mov   x0, x19                        ; &gi2c->se
ffff800080deb768:  97e95a77   bl    geni_se_resources_on           ; <-- i2c-qcom-geni.c:868
ffff800080deb76c:  2a0003e3   mov   w3, w0        <-- lr 指向这里（+0x380）
ffff800080deb770:  35000c00   cbnz  w0, ...<geni_i2c_probe+0x504>   ; if (ret) goto err_resources
ffff800080deb774:  f9400260   ldr   x0, [x19]                     ; x0 = gi2c->se.base
ffff800080deb778:  9101a003   add   x3, x0, #0x68                 ; base + GENI_FW_REVISION_RO(0x68)
ffff800080deb77c:  b9400063   ldr   w3, [x3]      <=== 崩溃 PC（+0x390）: 读 SE+0x68
ffff800080deb780:  d3483c63   ubfx  x3, x3, #8, #8                  ; FW_REV_PROTOCOL_MSK = GENMASK(15,8)
ffff800080deb784:  71000c7f   cmp   w3, #0x3                      ; 3 = GENI_SE_I2C
ffff800080deb788:  54000dc1   b.ne  ...<geni_i2c_probe+0x554>   ; proto != GENI_SE_I2C -> -ENXIO
```

### 1.3 源码对照

`drivers/i2c/busses/i2c-qcom-geni.c`（`geni_i2c_probe` 起于 781 行）：

| 行号 | 代码 | 反汇编落点 | 说明 |
|---|---|---|---|
| 795 | `gi2c->se.base = devm_platform_ioremap_resource(pdev, 0);` | 0x…b438 | 只做 ioremap，**不碰硬件** |
| 802/807 | `devm_clk_get(dev,"core")` / `"se"` | 0x…b46c | |
| 811-816 | `device_property_read_u32(dev,"clock-frequency")` | — | 失败即打印 `Bus frequency not specified, default to 100kHz` |
| 821-825 | `platform_get_irq` + `geni_i2c_clk_map_idx()` | — | |
| 836 | `devm_request_irq()` | — | |
| 847-862 | `geni_icc_get()` / `geni_icc_set_bw()` | — | |
| 864 | `clk_prepare_enable(gi2c->core_clk)` | — | |
| **868** | `ret = geni_se_resources_on(&gi2c->se);` | **0x…b768**（返回 0x…b76c） | 打开 wrapper s-ahb + se clk + pinctrl |
| **873** | `proto = geni_se_read_proto(&gi2c->se);` | **0x…b774~b77c** | **← 崩溃** |
| 874 | `if (proto != GENI_SE_I2C)` | 0x…b784 | 未执行到 |

`include/linux/soc/qcom/geni-se.h`：

```c
 82: #define GENI_FW_REVISION_RO     0x68
139: #define FW_REV_PROTOCOL_MSK     GENMASK(15, 8)
140: #define FW_REV_PROTOCOL_SHFT    8

324: static inline u32 geni_se_read_proto(struct geni_se *se)
325: {
326:     u32 val;
327:
328:     val = readl_relaxed(se->base + GENI_FW_REVISION_RO);   // ← 崩溃指令
329:
330:     return (val & FW_REV_PROTOCOL_MSK) >> FW_REV_PROTOCOL_SHFT;
331: }
```

`drivers/soc/qcom/qcom-geni-se.c:538` `geni_se_resources_on()` → `:516 geni_se_clks_on()`：

```c
static int geni_se_clks_on(struct geni_se *se)
{
    struct geni_wrapper *wrapper = se->wrapper;
    ret = clk_bulk_prepare_enable(wrapper->num_clks, wrapper->clks);  // wrapper "s-ahb"
    ...
    ret = clk_prepare_enable(se->clk);                                // SE "se" 时钟
}
```

### 1.4 崩溃前日志的顺序自洽性（重要推断依据）

崩溃前最后一条业务日志是 `Bus frequency not specified, default to 100kHz`（源码 816 行）。此后的 821/825/836/847/860/864/868 **全部没有打错误日志**，而 868 返回 0（`cbnz w0` 未跳转，所以执行到了 0x…b77c）。这说明：

- ID 表匹配、取中断、频率合法、request_irq、ICC 投票、`core_clk` 使能、`geni_se_resources_on()` **全部成功**；
- 崩溃发生在**第一次读 SE 寄存器**，不是"资源没准备好而报错"，而是"资源全部报成功后，硬件仍然不应答"。

---

## 2. 这一行读操作依赖的全部硬件资源，以及缺失/不符时的现象

`readl_relaxed(se->base + 0x68)` 一次读，背后依赖下列 7 项资源。逐项给出"DT 里缺它/写错它会发生什么"：

| # | 资源 | DT 属性（`i2c_hub_2` / `i2c_master_hub_0`） | 缺失/错误的表现 |
|---|---|---|---|
| 1 | **MMIO 基址**（唯一直接决定这条指令成败的） | 子节点 `reg = <0x0 0x00988000 0x0 0x4000>`；父节点 `ranges;`（恒等映射） | `ioremap` 永远成功（只建页表），**首读即 external abort**。若不在任何有效窗口内（如写成 `0x9c800000`），必崩。**本报告判定就是这一项。** |
| 2 | **QUP wrapper 的 S-AHB 时钟** | 父 `clock-names="s-ahb"; clocks=<&gcc GCC_QUPV3_I2C_S_AHB_CLK>` | 父节点 probe 失败/缺失时 `se->wrapper==NULL`，`clk_bulk_prepare_enable(NULL,...)` → **NULL 解引用 oops**（不是 external abort）。本机不是这条。 |
| 3 | **SE 的 `se` 时钟** | `clocks=<&gcc GCC_QUPV3_I2C_S2_CLK>`（dtb 里是 `0x61 0x4a`） | 取不到 → `-EPROBE_DEFER`/`-ENOENT` 报错退出；能取到但 GCC 侧该分支没实现/被 gate → 寄存器可读但读到 0 或 abort（**推断**）。 |
| 4 | **SE 的 `core` 时钟** | `clock-names="se","core"; clocks=<… S2_CLK, &gcc GCC_QUPV3_I2C_CORE_CLK>`（`0x61 0x45`） | `has_core_clk=true` ⇒ probe 864 行硬性 `clk_prepare_enable`，取不到直接失败；供上但 QUP core 域未起 → 访问 abort（**推断**）。 |
| 5 | **pinctrl** | `pinctrl-names="default"; pinctrl-0=<&hub_i2c2_data_clk>`（gpio20/21, function `i2chub0_se2`） | 只影响 SDA/SCL 引脚电气，**不影响 CPU 对 SE 寄存器的访问**；apply 失败 → `geni_se_resources_on` 返回错误 → probe defer，不会 abort。 |
| 6 | **interconnect (ICC)** | `interconnects = <&clk_virt MASTER_QUP_CORE_0 …>, <&gem_noc MASTER_APPSS_PROC &config_noc SLAVE_I2C …>; interconnect-names="qup-core","qup-config"` | 缺 path → `geni_icc_get()` 返回 `-ENODEV` → probe 直接退出（无 abort）；投票失败 → `-EIO` 退出。**不产生 external abort。** |
| 7 | **power-domain / opp** | `power-domains=<&rpmhpd RPMHPD_CX>; required-opps=<&rpmhpd_opp_low_svs>` | 缺失时不会报错但 CX 域可能未按 low_svs 起；若 CX 未上电则 SE 不响应 → **abort（推断，需实验排除）**。 |
| 8 | **中断** | `interrupts=<GIC_SPI 466 …>` | 只影响传输，不影响寄存器读。 |

**归纳**：能造成"`+0x68` 首读 external abort"的只有 **#1（地址）** 与 **#3/#4/#7（时钟/电源真没开）** 两类；#2/#5/#6 都会在到达这条指令之前就以错误码退出。所以定位问题等价于**区分"地址错"还是"时钟/电源没开"** —— 而 §3 的 DT 审计 + §4 的设备名证据已经指向"地址错"。

---

## 3. 现有 DTB 节点逐属性审计（原始 fdtget 输出）

对象：`/home/shrp/_tmp/nura_build/m2468.dtb`（137,392 B，80 个 `/soc@0` 子节点），源码 `/home/shrp/_tmp/lmp/sm8550-meizu-21note-m2468.dts`。

### 3.1 `/soc@0/geniqup@9c0000`（I2C master hub wrapper）

```
$ fdtget -p  m2468.dtb /soc@0/geniqup@9c0000
compatible reg clock-names clocks #address-cells #size-cells ranges status

  compatible      = qcom,geni-se-i2c-master-hub
  reg             = 0 10223616 0 8192          → 0x9c0000, size 0x2000
  clock-names     = s-ahb
  clocks          = 61 90                      → &gcc 0x5a = GCC_QUPV3_I2C_S_AHB_CLK
  #address-cells  = 2
  #size-cells     = 2
  ranges          =                            （空 = 恒等映射，1:1）
  status          = okay
```

结论：与 upstream `sm8550.dtsi:1630` 的定义、与厂商 DT 一致。**该 wrapper 无 `power-domains`/`interconnects`，upstream 同样没有**，不是缺失。

### 3.2 `/soc@0/geniqup@9c0000/i2c@988000`（SE#2，崩溃对象）

```
  compatible         = qcom,geni-i2c-master-hub
  reg                = 0 9994240 0 16384          → 0x988000, size 0x4000   ✅
  clock-names        = se core
  clocks             = 61 74 61 69                → S2_CLK(0x4a) + CORE_CLK(0x45)  ✅
  pinctrl-names      = default
  pinctrl-0          = 105                        → hub-i2c2-data-clk-state (gpio20/21, i2chub0_se2) ✅
  interrupts         = 0 466 4 0                  → GIC_SPI 466（厂商 DT 同为 466）✅
  #address-cells     = 1
  #size-cells        = 0
  interconnects      = 63 0 7  63 3 7  7 2 3  64 15 3
  interconnect-names = qup-core qup-config
  power-domains      = 66 0                       → &rpmhpd RPMHPD_CX ✅
  required-opps      = 39                         → &rpmhpd_opp_low_svs ✅
  status             = okay
  clock-frequency    = 400000                     ✅
  子节点：typec-retimer@1c (onnn,nb7vpq904m), pmic@8 (qcom,pm8008)
```

作为对照，**厂商原厂 DT**（`/home/shrp/m2468/merged_full.dts:28115`，反编译自 stock dtb）：

```
i2c@988000 {
    qcom,clk-freq-out = <0x61a80>;      /* 400 kHz */
    compatible = "qcom,i2c-geni";
    reg = <0x988000 0x4000>;            /* 同一个地址，说明硬件确实存在 */
    interrupts = <0 0x1d2 4>;           /* 466，一致 */
    clock-names = "se-clk", "core-clk";
    clocks = <… S2_CLK, … CORE_CLK>;    /* 同一对 GCC 时钟 */
    qcom,i2c-hub;                       /* 厂商私有标记，主线不需要 */
    status = "ok";
    cs35l43@40/41 { … }  fsa4480@42 { … }
}
```

**⇒ `m2468.dtb` 这一路 i2c 的属性是正确且完整的；upstream 缺的只有厂商私有的 `qcom,i2c-hub` / `pinctrl-1(sleep)`，二者都不影响寄存器访问。**

### 3.3 与崩溃日志的三处硬矛盾 ⇒ 崩溃那次启动用的 DTB 不是这份

| | 崩溃日志 | 工作区 `m2468.dtb` | 矛盾性质 |
|---|---|---|---|
| ① | `geni_i2c 9c800000.i2c` → reg 翻译结果 **0x9c800000** | `reg` = 0x988000 → 设备名应为 `988000.i2c` | **决定性**：设备名由 `of_translate_address()` 生成（见 §4.1），直接暴露 reg |
| ② | `Bus frequency not specified, default to 100kHz` ⇒ 该节点**没有** `clock-frequency` | 有 `clock-frequency = <400000>` | 决定性：该属性存在时绝不打印此句 |
| ③ | 依赖环路径写 `/soc@0/geniqup@9c0000/i2c@9880000/typec-retimer@lc`（节点名 7 位十六进制 `9880000`，且 `@lc` 明显是 `@1c` 的字符误读） | 节点名 `i2c@988000`（6 位） | 说明当时 DT 里节点名与 reg 都多写了一位/两位 0 |

另外我在 **ESP 镜像（`esp.img`，FAT32，268 MB）** 里把全部 FDT 副本扫了一遍，共 4 种互不相同的 DTB，**没有任何一份含 `0x9c800000`**：

```
[4f2b1f50] sz=113810 model='Qualcomm Technologies, Inc. Kalama v2 SoC'  i2c@988000 reg=0 9994240 0 16384 clkfreq=<无>
[13b3500f] sz=114109 model='Qualcomm Technologies, Inc. Kalama v2 SoC'  i2c@988000 reg=0 9994240 0 16384 clkfreq=<无>
[877e9e22] sz=114093 model='Meizu 21 Note DTB-FROM-ESP'                 i2c@988000 reg=0 9994240 0 16384 clkfreq=<无>
[de357b52] sz=137380 model='Meizu 20 (m2381)'                           i2c@988000 reg=0 9994240 0 16384 clkfreq=400000
```

（扫描脚本见 §7。注意其中三份 **缺 `clock-frequency`**，能解释日志 ② 但解释不了 ①；`de357b52` 就是 m2381 的 nura dtb 副本。）

由此得到两种必须区分的可能：

- **可能甲（我判定为主因）**：日志地址抄录准确 ⇒ 当时启动的 DTB 是一份**已不在磁盘上**（或被 ESP 里已被删除簇覆盖）的、`reg` 被写成 `0x9c800000` 的错误 DTB。那么根因就是 **DT 的 reg 地址错误**。
- **可能乙**：`9c800000` / `9880000` 是誊写时多打的 0（注意同一段日志里 `typec-retimer@lc` 已确认是 `@1c` 的误读，说明该日志是人工/OCR 转录）⇒ 那么真正崩的是 `reg=0x988000` 的正确地址，根因退回到 **时钟/电源域未真正打开（#3/#4/#7）**。

**判别方法（不改代码、只看现有材料）**：arm64 oops 的 `Mem abort info` 块一般不含 FAR，但如果照片/串口日志里存在 `FAR:`/`far` 字段或 `pgd=…` 之后的地址行，看它等于 `0x9c800068`（⇒ 甲成立，地址错）还是 `0x988068`（⇒ 乙成立，需查时钟）。没有 FAR 时用 §5 的 E4/E5 实验判别。

### 3.4 这个节点为什么会在 DT 里（来源溯源）

- `sm8550-meizu-21note-m2468.dts` 与 `sm8550-meizu-20.dts`（nura 项目，m2381）**只差 4 处字符串**（model / root compatible / pmic-glink compatible / sndcard compatible），`diff` 仅 8 行（64,866 → 64,877 字节）：

```
$ diff sm8550-meizu-20.dts sm8550-meizu-21note-m2468.dts
< model = "Meizu 20 (m2381)";        > model = "Meizu 21 Note (m2468)";
< compatible = "meizu,meizu-20",…    > compatible = "meizu,21note",…
```

- 因此 `&i2c_master_hub_0 { status="okay" }`（1388 行）、`&i2c_hub_2 { clock-frequency; typec-retimer@1c; }`（1471 行）、`&i2c_hub_2 { pm8008i: pmic@8; }`（1580 行，**同一 label 被覆盖两次，dtc 合并**) 全部是从 m2381 的 nura dts 整段搬过来的。
- 这本身**没有错**：SM8550 上该 hub/该 SE 是真实存在的（厂商 DT 同址挂了 cs35l43×2 + fsa4480），m2381/m2468 共用同一套 QUPV3_I2C。

---

## 4. 根因判定

### 4.1 硬证据：设备名里的十六进制就是 `reg` 的翻译结果

`drivers/of/device.c:288`

```c
void of_device_make_bus_id(struct device *dev)
{
    struct device_node *node = dev->of_node;
    while (node->parent) {
        reg = of_get_property(node, "reg", NULL);
        if (reg && (addr = of_translate_address(node, reg)) != OF_BAD_ADDR) {
            ...
            dev_set_name(dev, dev_name(dev) ? "%llx.%pOFn:%s" : "%llx.%pOFn",
                         addr, node, dev_name(dev));       // ← 设备名 = 翻译后的地址 + 节点名
            return;
        }
        ...
```

- `%llx` = `of_translate_address(node, reg)`（父节点 `ranges;` 为空 ⇒ 恒等 ⇒ 就是 `reg` 的第 1 个地址）
- `%pOFn` = 节点名（`i2c`，没有单元地址）

所以 **`geni_i2c 9c800000.i2c` 等价于"该节点 reg 译出 0x9c800000"，这是内核自己算出来的，不可能是打印错误**（除非整段日志是人工转录时改错了数字）。

`0x9c800000` 与真实地址的差异：正确 `0x988000`，多写了两位十六进制 0 —— 典型的**手改/AI 改 dts 时把 `reg = <0x0 0x00988000 0x0 0x4000>` 写成了 `<0x0 0x09c80000 0x0 0x4000>` 或 `<0x0 0x9c800000 …>`** 之类的地址串损坏。

### 4.2 ESR 与指令一致

`ESR = 0x96000010`：EC=0x25（Data Abort，取自当前 EL）、IL=1、**WnR=0（读）**、ISV=0、DFSC=0x10（**synchronous external abort**，非页表 walk）。
与 `ldr w3,[x3]`（32 位读）完全吻合；若是写错、或页表问题，DFSC 会是 0x04~0x0F 一类翻译错误而非 external abort。**⇒ 总线层从设备未应答，而不是软件权限/映射问题。**

### 4.3 定案

| 结论 | 置信度 | 依据 |
|---|---|---|
| 崩溃点 = SE `+0x68` 首个寄存器读（`i2c-qcom-geni.c:873`） | **确定** | 反汇编逐条对齐 + lr 指向 `geni_se_resources_on` 返回点 + 前后资源全部成功 |
| 崩溃原因类别 = 总线从设备未应答（地址错 **或** 时钟/电源未开） | **确定** | ESB/DFSC + 指令语义 |
| 崩溃当时 DT 的 `reg` = `0x9c800000`（≠ 0x988000） | **高**（前提：日志数字为真实抄录） | `of_device_make_bus_id()` 机制 + 缺 `clock-frequency` + 节点名 7 位，三条独立矛盾 |
| 崩的那次启动 ≠ 工作区 `m2468.dtb` | **高** | 同上；另 ESP 内 4 份 DTB 均不含该地址 ⇒ 刷入的是第三份（更早/已删）DTB，或日志被误抄 |
| 若地址其实正确（可能乙）：根因为 SE 时钟/PD 未真正开启 | 未排除 | 需 E4/E5 实验；主线 hub 路径只 enable `s-ahb`+`se`+`core`，不碰任何 reset/GDSC 显式控制，理论上够用 |

---

## 5. 最小改动实验方案（递进，5 个）

> 所有实验都遵守一条铁律：**一次只改一处，且必须先证明"刷进去的 DT 真的生效"** —— 因为本机存在两条 DT 供给路径：Mu-Silicium 的 `FdtBlob`（`/home/shrp/Mu-Silicium/Platforms/Meizu/m2468Pkg/FdtBlob/sm8550-meizu-21note.dtb`，由 `m2468.fdf:104 RAW=` 编进 UEFI）与 ESP 里的 `/dtb` 文件（`build_esp_zboot.sh` 会把 `arch/arm64/boot/dts/qcom/sm8550-meizu-21note.dtb` 拷成 ESP 根目录的 `dtb`）。**两者内容不一致时，你看到的现象会和 dts 对不上——本次事故极可能就是这个。**

### E1（前置，必做）：确认内核实际吃的是哪份 DT

在 dts 的 `/` 节点先加一个不会看错的标记，两份都更新：

```dts
/ {
    model = "Meizu 21 Note (m2468) DBG-E1";
};
```

```bash
bash /home/shrp/.../build_m2468.sh                # 产出 nura_build/m2468.dtb
cp /home/shrp/_tmp/nura_build/m2468.dtb \
   /home/shrp/Mu-Silicium/Platforms/Meizu/m2468Pkg/FdtBlob/sm8550-meizu-21note.dtb
cp /home/shrp/_tmp/nura_build/m2468.dtb \
   /home/shrp/linux-6.14.11/arch/arm64/boot/dts/qcom/sm8550-meizu-21note.dtb
bash build_mu_m2468.sh && bash flash_v2.sh        # Mu 侧
# 若要同时更新 ESP 侧：bash build_esp_zboot.sh（需要 /mnt/esp 可挂）
```

**判定**：开机 dmesg 里 `Hardware name:` 出现 `DBG-E1` ⇒ 这份 DT 生效；否则**你刷的不是它**，先解决供给路径（例如 Mu 的 FDT 表被 ESP `/dtb` 覆盖，或 fdf 里的 blob 没重编）。

### E2：只关掉这一路 i2c（确认崩溃归属）

```dts
&i2c_hub_2 {
    status = "disabled";        /* 保留 i2c_master_hub_0 为 okay */
};
```

**预期**：`geni_i2c 9c800000.i2c`/`988000.i2c` 相关的 external abort 消失，内核继续跑完 initcall（可能卡在别的 defer）。
**判定**：若仍以同样 PC abort ⇒ 崩的不是这一路（回去查是否有第二个 geni_i2c 节点被 enable，如 `&i2c0/&i2c4/&i2c10` 或另一路 hub SE）。

### E3：保留控制器、摘掉子设备（区分"控制器自身" vs "子设备访问"）

```dts
&i2c_hub_2 {
    status = "okay";
    clock-frequency = <400000>;
    /delete-node/ typec-retimer@1c;
    /delete-node/ pmic@8;          /* pm8008i，删掉可避免它再往总线上发事务 */
};
```

**预期**：**仍然 abort**（因为崩点在控制器 probe 的 `geni_se_read_proto`，任何子设备都还没开始 probe）。
**判定**：若"不再 abort 且 adapter 注册成功" ⇒ 我的读点判断需修正，真正触发者是子设备 probe 时的一次总线事务（那时应看到 `nb7vpq904m`/`pm8008` 的日志）。

### E4：把 reg 写成"确定值"（验证地址假设＝根因）

不依赖 label 继承，显式重写节点（保留在 `&i2c_master_hub_0 { }` 之后，dtc 会合并/覆盖同址节点）：

```dts
&i2c_hub_2 {
    reg = <0x0 0x00988000 0x0 0x4000>;   /* 硬写，排除任何继承/篡改 */
    clock-frequency = <400000>;
    status = "okay";
};
```

**预期**：`geni_i2c 988000.i2c`，不再 abort，日志出现 `Geni-I2C` adapter 注册（随后 typec-retimer/pm8008 才开始 probe，可能各报自己的错）。
**判定**：这个实验同时是"修复验证"。若此时也 abort，且设备名变成 `988000.i2c` ⇒ **地址不是主因**，转 E5（时钟/电源）。

### E5（仅在 E4 仍 abort 时）：区分"整个 hub 不通" vs "单 SE 问题"

```dts
&i2c_hub_0 {            /* 同一 wrapper 下的 SE#0，地址 0x980000 */
    status = "okay";
    clock-frequency = <100000>;
};
```

**预期与判定**：
- **所有 hub SE 都 abort** ⇒ wrapper 层问题（`s-ahb`/`GCC_QUPV3_I2C_CORE_CLK` 没真正起、CX 域没上电、或该 QUP 被 bootloader 关在某个 secure/GDSC 状态）。此时查 `dmesg | grep -i "geni_se_qup\|gcc\|rpmhpd"`，确认 `9c0000.geniqup` 是否 probe 成功、`clk_summary` 里 `qupv3_i2c_*` 的 enable_cnt。
- **只有 0x988000 那一路 abort** ⇒ 该 SE 在该机型上确实被别的东西占用/未接（回到"地址/实例不存在"分支，见 §6）。

---

## 6. 关于"该 i2c 控制器在本机不存在"这一假设

**先给结论：不成立（95%）。** 该 SE 在本机真实存在且厂商在用：

- 厂商 DT（反编译自本机 stock dtb）`/soc/qcom,qupv3_i2c_geni_se@9c0000/i2c@988000`：`status="ok"`，`qcom,i2c-hub`，`qcom,clk-freq-out=<400000>`，其下挂 **cs35l43@40 / @41（听筒+扬声器智能功放）与 fsa4480@42（Type-C mux）**；
- 与主线 DT 的地址/中断/时钟/ICC 完全对得上（§3.2 对照表）。

DT 里存在它的原因（§3.4）：`sm8550-meizu-21note-m2468.dts` 是从 nura 的 `sm8550-meizu-20.dts`（m2381）整段搬来的，`&i2c_master_hub_0` + `&i2c_hub_2{typec-retimer}` + `&i2c_hub_2{pm8008i}` 三个 override 都是原样继承。**搬这一路本身是对的**（同 SoC、同 hub、同 retimer 方案），错的是搬运/编辑过程中 `reg`（以及 `clock-frequency`）被弄坏了 —— 这正是 §3.3 三条矛盾的来源。

正确做法（按优先级）：

1. **补对属性（推荐）**：`reg = <0x0 0x00988000 0x0 0x4000>`、`clock-frequency = <400000>`、父节点 `geniqup@9c0000` 保持 `status="okay"` 且 `ranges;`、`clock-names="s-ahb"`。这就是 E4。
2. **禁用（仅用于定位/降级）**：`&i2c_hub_2 { status = "disabled"; }`。代价：Type-C 的 SS 通道重定时器（nb7vpq904m）与 pm8008i 相机 PMIC 都不工作（`pmic_glink_altmode` 会报 `failed to acquire mode-switch`，`/sys/class/typec` 空）。**不要**用它当"修复"。
3. **删除节点（不要做）**：会连带删掉 `pmic@8`(pm8008i) 与 `typec-retimer@1c`，且与 upstream dtsi 的定义冲突（dtsi 里还有 `i2c_hub_2` label，删不掉，只会得到"节点还在但状态不对"的半吊子结果）。

---

## 7. 可复现命令清单

```bash
# 1) 符号 + 反汇编
cd /home/shrp/linux-6.14.11
aarch64-linux-gnu-nm vmlinux | grep -w geni_i2c_probe
aarch64-linux-gnu-objdump -d --start-address=0xffff800080deb3ec \
    --stop-address=0xffff800080debaa0 vmlinux | sed -n '/deb760:/,/deb790:/p'

# 2) 源码行
sed -n '781,900p' drivers/i2c/busses/i2c-qcom-geni.c
sed -n '316,332p' include/linux/soc/qcom/geni-se.h
sed -n '505,556p' drivers/soc/qcom/qcom-geni-se.c
sed -n '288,325p' drivers/of/device.c

# 3) DT 审计
D=/home/shrp/_tmp/nura_build/m2468.dtb
for p in /soc@0/geniqup@9c0000 /soc@0/geniqup@9c0000/i2c@988000; do
  echo "## $p"; for pr in $(fdtget -p $D $p); do echo -n "  $pr="; fdtget $D $p $pr | tr '\n' ' '; echo; done
done
fdtget -l $D /soc@0/geniqup@9c0000/i2c@988000          # 子节点
dtc -I dtb -O dts $D -o /tmp/m.dts                     # 全量反编译

# 4) 厂商 DT 对照（真实硬件存在性）
grep -n "i2c@988000" -A 20 /home/shrp/m2468/merged_full.dts | head -40

# 5) 扫描 ESP 镜像里全部 DTB 副本（找"到底刷了哪份"）
python3 - <<'EOF'
import struct,subprocess,hashlib
d=open("/mnt/c/Users/Administrator/AppData/Local/Temp/ksuwork/esp.img","rb").read()
i=0;seen=set()
while True:
    i=d.find(b"\xd0\x0d\xfe\xed",i)
    if i<0: break
    sz=struct.unpack(">I",d[i+4:i+8])[0]
    if 0x1000<sz<0x200000 and i+sz<=len(d):
        so=struct.unpack(">I",d[i+8:i+12])[0]
        if 0x30<so<sz:
            h=hashlib.sha1(d[i:i+sz]).hexdigest()[:8]
            if h not in seen:
                seen.add(h); f=f"/tmp/esp_{h}.dtb"; open(f,"wb").write(d[i:i+sz])
                print(h, sz, subprocess.run(["fdtget","-t","s",f,"/","model"],
                      capture_output=True,text=True).stdout.strip())
    i+=1
EOF

# 6) 开机后自查（设备上）
dmesg | grep -iE "geni_se_qup|geni_i2c|Bad data|abort"
cat /proc/device-tree/model; echo
cat /proc/device-tree/soc@0/geniqup@9c0000/i2c@988000/reg | hexdump -C   # 核对 reg 实际值
```

---

## 8. 给下一步的一句话

**先做 E1**：本次崩溃日志与工作区 DTB 的三条矛盾说明"刷进去的 DT ≠ 你改的 DT"；把这条链路（Mu `FdtBlob` vs ESP `/dtb`）锁死以后，再按 E4 把 `reg` 硬写成 `<0x0 0x00988000 0x0 0x4000>` + `clock-frequency=<400000>` 编译验证一遍，崩溃即可判定消除或转入 E5（时钟/电源域）分支。
