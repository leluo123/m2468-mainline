# 触摸真相：GENI SE FIFO 通路被 XBL latch（m2468 / GT9916）

> 2026-10-30 | 魅族 21 Note (m2468, SM8550) | mainline Linux 7.3.0

## 一句话结论

触摸 probe 报 `SPI transfer timed out (-110)` **不是触摸 IC 的问题，是 GENI SE 的 FIFO 数据通路被 bootloader 关死且驱动从未重新打开**。

## 完整链条（每步都有证据）

```
1. Mu/UEFI 引导，没有 QSEE / 没有 SE firmware
   → geni_load_se_fw() 从未执行（qcom-geni-se.c:1428）
   → 而清 FIFO_IF_DISABLE 的代码只在这个函数里（:1529）
   → SE_FIFO_IF_DISABLE (0x2008) bit0 保持 XBL 留下的 1

2. geni_se_select_fifo_mode()（:381）只清 GENI_DMA_MODE_EN，不清 0x2008
   → 驱动以为自己在用 FIFO，实际 FIFO 通路在硬件上不存在

3. spi_sync() 发出命令 → M_CMD_DONE 永远不来（唯一的 finalize 点在 spi-geni-qcom.c:980）
   → SPI core 看门狗超时（spi.c:1674-1685）→ -ETIMEDOUT (-110)

4. 这个 -110 与触摸 IC 完全无关：
   - IC 没电 → 只会读回 0xFF，然后 dev_confirm 失败（另一种错误码）
   - IC 没复位 → 同上
   - IC 没固件 → mainline 不下载固件（core.c:17-23 全文无 request_firmware）
                    缺固件只会报 -EINVAL / checksum error
```

## 现场验证命令（一行闭环）

```bash
dmesg | grep -c "FIFO mode disabled, but couldn't get DMA"
# 返回 1 ⇒ 根因确认，别再往芯片/接线/供电方向查
```

本机实测：**命中**（`[11.501917] geni_spi a90000.spi: FIFO mode disabled, but couldn't get DMA, fall back to FIFO mode`）

## 修复（E30）

`drivers/soc/qcom/qcom-geni-se.c` 的 `geni_se_select_fifo_mode()`，在清 DMA 模式之后加一行：

```c
/*
 * E30: The FIFO interface disable bit is left set by the bootloader when
 * no SE firmware is loaded (e.g. Mu/UEFI boot without QSEE). Without
 * clearing it the FIFO data path stays dead and every spi_sync() times
 * out with -ETIMEDOUT even though the driver believes it uses FIFO.
 */
geni_clrbits32(se->base + SE_FIFO_IF_DISABLE, FIFO_IF_DISABLE);
```

其中：
- `SE_FIFO_IF_DISABLE = 0x2008`（qcom-geni-se.c:237）
- `FIFO_IF_DISABLE = BIT(0)`（include/linux/soc/qcom/geni-se.h:177）

## 被推翻的错误猜测（重要，防止重走）

| 曾经的猜测 | 真相 |
|---|---|
| `CONFIG_QCOM_GPI_DMA=y` 会因 TrustZone 崩溃 | 与 TZ 无关；`gpi.c` 全文无 `scm`/`firmware`/`pas_`/`tz`。真因是 initcall 时序：`gpi_init` 级 4、`spi_geni` 级 6，`=y` 时 gpi 先注册成功，spi probe 时真的去碰硬件（而这枚 GSI 块在 Mu 引导下从未被固件 provisioning，DT 里也没有 clocks/power-domains/interconnects） |
| 触摸没电（ldo9 没开） | ldo9 已使能 2960mV；`0mA` 是假读数（PMIC 驱动没有 `get_current_limit`，`core.c:6580` 把 -EINVAL 截断成 0） |
| `use=0` 说明没消费者 | Mu dtb 的 avdd 指到 ldo14(3.2V) 而没引用 ldo9——这是**真实的 DT 错误**，但**不是当前 -110 的原因** |
| reset 极性可能错 | `<0x4a 0x18 0x01>`（GPIO_ACTIVE_LOW）正确；改成 ACTIVE_HIGH 会把芯片按在复位 |
| 缺固件 | mainline 完全不下载固件；固件缺失只会报 -EINVAL/checksum |
| 需要 GPI DMA 才能工作 | 不需要；FIFO 通路本来可用，只是被 latch 住 |

## 触摸硬件的正确配置（ROUTE-I/ROUTE-L 交叉验证）

```yaml
IC:        Goodix GT9916（原厂 compatible = goodix,brl-d）
总线:      SPI，QUP a90000（不是 i2c！）
CS:        reg = <0>（SPI 片选 0）
频率:      15 MHz (0xe4e1c0)，与原厂一致
reset:     TLMM gpio24，<0x4a 0x18 0x01> = ACTIVE_LOW
irq:       TLMM gpio25，<0x19 0x02> = EDGE_FALLING
avdd:      应该是 L9B (vreg_l9b_2p9, 2.96V) —— Mu dtb 当前错写成 ldo14(3.2V)
vddio:     L12B (vreg_l12b_1p8, 1.8V) —— 正确
pinctrl:   <0x86 0x87> = ts-irq-state(gpio25) + ts-reset-state(gpio24)
SPI 四线:  <0x8a 0x8b> = gpio44/45/46 (data/clk) + gpio47 (cs)，function = qup1_se4
尺寸:      1264 x 2780
```

## 关键源文件位置

```
驱动:    /home/shrp/lmp73/drivers/input/touchscreen/goodix_berlin_core.c
         /home/shrp/lmp73/drivers/input/touchscreen/goodix_berlin_spi.c
SPI:     /home/shrp/lmp73/drivers/spi/spi-geni-qcom.c（:681 fifo_disable, :690 defer, :694-702 三路分支, :980 finalize）
SE:      /home/shrp/lmp73/drivers/soc/qcom/qcom-geni-se.c（:237 寄存器, :381 fifo_mode, :1428 load_fw, :1529 唯一清位点）
头文件:  /home/shrp/lmp73/include/linux/soc/qcom/geni-se.h:177
原厂DT:  /mnt/c/Users/Administrator/_tmp/m2468_fw/dtbo/entry0.dts（goodix 节点在 ~15520-15700）
```

## 原厂是怎么工作的（对比）

原厂不是"另一条路"，而是**四件套齐全**：
1. 基座 dtb 里 `spi@a90000` 是 `disabled`
2. dtbo `fragment@78` 把它改成 `okay` 并挂上 `goodix-berlin@0`
3. `goodix_ts.ko`（vendor_boot ramdisk 里，451KB，vermagic 5.15.119，依赖 `gh_rm_drv`/`gh_irq_lend` = Gunyah）
4. `/vendor/firmware` 里的 `goodix_firmware.bin` + `goodix_cfg_group.bin`

原厂走 `qts,trusted-touch-mode = "vm_mode"`，把整个 SE 交给 Gunyah 虚拟机，**所以原厂路径下 SE 是由 TZ/VM 完整初始化的**，FIFO 不会处于 latch 状态。

mainline 直接在宿主访问 SE，就必须自己补上"清 FIFO latch"这一步。
