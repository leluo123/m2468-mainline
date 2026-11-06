# nura（RiverKawa271828）魅族 20 / m2381 主线 DTS 方法论全解

> 调研对象：GitHub `RiverKawa271828`（昵称 nura / 提交署名 `ri`）的魅族 20（m2381，SM8550/kalama）
> postmarketOS + mainline Linux 移植。
> 调研日期：2026-10-27。方法：GitHub API（tree / commits?path）+ raw（gh-proxy 包装）+ 逐字读原文。
> 所有"证据"小节都给出**仓库路径**与**原文摘录**；凡属推断的，明确标 `【推断】`。

---

## 0. 结论摘要（先看这 8 条）

1. **DTS 不是从原厂 dtbo 反编译出来的整文件，也不是抄 sm8550-mtp/hdk。** 它的**骨架**来自第三方公开树
   `github.com/silime/linux` 分支 `7.3.0-dev` 的 `arch/arm64/boot/dts/qcom/sm8550-meizu-20-inf.dts`
   （魅族 20 **Infinity** 参考 DTS，45,692 B）。nura 把它拷进自己对该树的本地分支
   `meizu20-m2381-local`，改成 m2381，再导出到 fork `linux-mobile-ports` 分支 `meizu20-t4b`。
   证据：pmaports APKBUILD 注释原文 + 首个 DTS 提交信息 `(taken from silime tree meizu20-m2381-local tip 62b675446ca2)`。
2. **"原厂真值"来自三源 corpus，而不是一份完整反编译 DTS**：`base` = vendor_boot 里的 base DTB、
   `entry9` = dtbo 第 9 条 overlay（本机 `ro.boot.dtbo_idx=9`）、`RT` = ABL 加工后的 runtime FDT
   （Android 跑起来时 `/sys/firmware/fdt`）。三源 SHA256 固化在 `corpus/SHA256SUMS`。
3. **v2/v3 是一次"factory-first 白名单式重建"**：不继承任何 Infinity 派生内容，每个节点/属性必须
   "持证上岗"（三源之一 或 主线 binding 必然性），证不出来的**降级为注释桩**（相机、震动都曾是这样）。
4. **每个属性都带出处标签**，写在 DTS 注释里：`【A：…】`（原厂 corpus 值，48 处）、`【D：…】`（自主判决/
   战役产物，21 处）、`【B：…】`（主线 binding 必然性，含 `【A/B】`）、`【RT xxx】`（逐轨 RT 原值，45 处）。
   逐行台账本体 `LEDGER.md` 在私有工作区，**未公开**（见 §9）。
5. **取值判定靠"三源对账 + 上机单变量 A/B"双轨**：能对账的先对账（RPMH 75 轨、reserved-memory 全表、
   audio 分片），对不出的才上机做单变量实验，判据是**可重复次数**（如 `真睡唤醒 5/5 全花`、`knockout 臂 5/5`）。
6. **DTS 的"编译期"验证极轻但很硬**：每轮 `cpp + dtc` 编过 + **DTB 字节数与基线对比**
   （例："编证：cpp+dtc 绿 135782B（HEAD 基线 136352B，delta=WCD 摘除量；警告同族 17=17）"）。
7. **DTS 交付链的唯一性铁律**：DTB 只从**同一个 apk** 抽，塞进 Mu 的 `FdtBlob`，`verify.sh` 做
   sha256 对拍；`Mu` 只在 DTS 变时才重编（"FV DTB = 内核唯一 DT 源"）。
8. **这套方法可平移**到同 SoC 另一机型（如魅族 21 Note / SM8550），因为它的核心不是"某个 DTS"，
   而是 **corpus 三源 + 台账 + 审计 + 单变量判据** 四件套；但**必须重做 corpus**（三源全部换机型），
   且 `remoteproc memory-region`、`adspslpi`、`ramoops` 这类"固件合约面"**不能照抄 base 值**（§8）。

---

## 1. 可达性盘点（哪些读到了，哪些没有）

### 1.1 读到全文（公开仓）

| 仓库 / 分支 | 文件 | 用途 |
|---|---|---|
| `linux-mobile-ports` @ `meizu20-t4b` | `arch/arm64/boot/dts/qcom/sm8550-meizu-20.dts`（64,866 B / 2,046 行） | 主证据，v3b+ 现状 |
| 同上 | 该文件 25 条提交历史（API `commits?path=`） | 迭代阶梯 |
| 同上 | `README.md`（分支/基线/上游化政策） | 血统与政策 |
| `pmaports` @ `phoenix` | `device/downstream/linux-meizu-meizu20/APKBUILD` | **血统原文**（silime 出处） |
| 同上 | `device/downstream/device-meizu-meizu20/APKBUILD`（34 KB 注释） | 用户态契约、i2c 纪律 |
| 同上 | `linux-meizu-meizu20/0001-...add-Meizu-20-m2381-device-tree.patch`（60,698 B，冻结档） | 旧版 DTS 快照 |
| `Mu-Silicium` @ `meizu20-mars-port` | `Platforms/Meizu/m2381Pkg/FdtBlob/{sm8550-meizu-20.dtb,Source.txt}` | **交付链台账**（逐轮 dtb sha） |
| `nura-meizu-m2381` @ `master` | `AGENTS.md`(76 KB)、`docs/{DESIGN,PIPELINE,BOOT-CHAIN-RE,AUDIO-METHOD,PANEL-CORRUPTION,SUSPEND-S2IDLE}.md`、`script/{build-kernel,build-mu,verify}.sh`、`docs/FLASHING.md`、`MANIFEST.md` | 方法论 / 纪律 / 验证链 |
| `silime/linux` @ `7.3.0-dev` | `arch/arm64/boot/dts/qcom/sm8550-meizu-20-inf.dts`（45,692 B） | **DTS 骨架原件（已下载比对）** |

### 1.2 取不到（必须说明，不编造）

| 想读的 | 状态 | 原因 |
|---|---|---|
| `meizu20-m1/dts/factory-first/LEDGER.md`（逐行台账） | **取不到** | 在私有工作区 `meizu20-m1/`，四个公开仓的 tree 里均无该路径（`nura-meizu-m2381` 全树已拉，无 `dts/`；内核仓根目录无 `dts/`） |
| `meizu20-m1/dts/factory-first/reports/AUDIT-T4-20261004.md` | **取不到** | 同上（DTS 里 15 次引用它的章节号，可反推结构，见 §5） |
| `corpus/SHA256SUMS`、`corpus/vboot_a.fdt0.dts`、`corpus/merged.entry9.dts`、`deepseek-round2-materials/` | **取不到** | 私有工作区（且含原厂提取件，作者政策"stock 提取件零入仓"） |
| `reports/PANEL-GROUND-TRUTH.md`、`docs/meizu20/experiment-log.md`（（九十）等）、`silime-exit-carry-list.md` | **取不到** | 同上，私有 |
| pmos_linux 私有仓 `AGENTS.md`（硬定律/坑册单一事实源） | **取不到** | 无远端 |

> 因此本报告中凡涉及 LEDGER / AUDIT-T4 **内部**的格式与结论，均以 **DTS 内嵌引用（15 处 AUDIT-T4 引用、
> 48 处 A 标签、21 处 D 标签）+ `FdtBlob/Source.txt` + 25 条提交信息**为一手替代证据，并逐条标明来源。
> 未做任何"看起来像"的补写。

---

## 2. 问题 1：DTS 最初从哪来？（完整证据链）

### 2.1 一句话

**骨架抄自 silime 的公开树 `silime/linux`（分支 `7.3.0-dev`）里的 `sm8550-meizu-20-inf.dts`（魅族 20 Infinity
参考 DTS）→ 在本地分支改造成 m2381 → v2/v3 用本机原厂三源 corpus 做白名单式重建 → 之后 12 轮设备日迭代。**

### 2.2 证据 1：pmaports APKBUILD 的 doctrine 注释（原文）

路径：`pmaports/device/downstream/linux-meizu-meizu20/APKBUILD`（`phoenix` 分支）

```
# Doctrine ("干净主线内核 + 我们的 DTS"): upstream = silime's public
# 7.3.0-dev tree (mainline 7.3.0-rc3 + SM8550 device enablement incl. the
# Meizu 20 Infinity reference DTS); our entire delta is the single DTS
# patch below. Local dev tree: meizu20-m1/m1-work/silime-linux (branch
# meizu20-m2381-local); provenance snapshot: meizu20-m1/kernel/.
```

以及同一文件下方的溯源更正（说明他连"血统误说"都做了勘误）：

```
# fork base = silime master 587858367581 (09-14, 零 meizu 文件; 派生底本
#  = 他 7.3.0-dev 分支的 sm8550-meizu-20-inf.dts, 非携带 commit).
# (旧注 _commit=3a94ad18d21d 系"审计区间"误说, (六十四) 判废.)
url="https://github.com/silime/linux"
```

关键点：**fork 基线 `587858367581` 里"零 meizu 文件"**——即 DTS 不是 fork 自带、不是上游 pmaports 的
m2381 支持（当时 pmaports 只有 meizu 旧机型 `mblu2`/`turbo` 的 downstream 包），而是**从 silime 的另一条
开发分支单独拿的一份参考 DTS**，且它**不是被他 cherry-pick 的提交**（"非携带 commit"）。

### 2.3 证据 2：首个 DTS 提交的信息与文件头

提交 `27be20775`（2026-09-29）：

```
arm64: dts: qcom: add Meizu 20 (m2381) device tree

Our m2381 DTS: true /memory, no stdout-path, touch 1080x2400, panel
te-source mdp_vsync_p, panel supplies state from device deployment.

(taken from silime tree meizu20-m2381-local tip 62b675446ca2)
```

该提交新增的 `sm8550-meizu-20.dts`（1,776 行）文件头是**双 SPDX 双版权**，第二个版权人是
Teguh Sobirin（SM8550 移植圈常见上游骨架作者），第一行 model 还写着 `Meizu 20 Inf`：

```dts
// SPDX-License-Identifier: GPL-2.0-only
/*
 * Device Tree Source for Meizu 20 Inf (SM8550/Kalama)
 * Copyright (c) 2026 Meizu Technologies
 */
// SPDX-License-Identifier: BSD-3-Clause
/*
 * Copyright (c) 2025, Teguh Sobirin.
 */
```

### 2.4 证据 3：我直接下载了骨架原件并比对

`silime/linux` @ `7.3.0-dev` → `sm8550-meizu-20-inf.dts` = **45,692 B**，能 200 拉到；
`master`/`main` 分支该路径 404（说明就是这条 dev 分支的私货）。
与本仓 v1 DTS 对比：nura 版 1,775 行，silime 版 2,090 行，diff 删除 1,734 行 / 新增 1,463 行
（整文件顺序重排，属"重写"而非"打补丁"）。
silime 版 vs nura v1 的**语义差异**（节选，均为实物核对）：

| 项 | silime `-inf.dts` | nura v1（m2381） |
|---|---|---|
| `model` / `compatible` | `Meizu 20 Inf` / `meizu,meizu-20-inf` | `Meizu 20 (m2381)` / `meizu,meizu-20` |
| `/memory` | **完全没有** memory 节点（裸跳必 panic） | **从 stock `/sys/firmware/fdt`（2026-09-21 收割）抄 8 段 reg**，注释说明"裸跳没人填 size ⇒ paging_init panic" |
| `chosen` | `stdout-path = "serial0:115200n8"` | **故意删掉**（UEFI 链要 fbcon，不能被 serial 抢 console） |
| 摄像 | 继承 IMX563 相机块（Infinity 的） | 删除（`7a693447b`:"drop inherited IMX563 camera block"） |
| 无线充 | 有 wireless supplies | 禁用（`f012c798b`） |
| 音频 | WCD 全链 + `meizu-20-inf-sndcard` | 先保持，后按 m2381 实测改 CS35L45 直驱 |

> 结论：**"从零"其实不是从零**——第一步是"拿同 SoC 同厂兄弟机型的参考 DTS 当脚手架"，第二步
> 才用本机原厂 corpus 把脚手架上的东西一件件换掉。这与"从 sm8550-mtp 复制改写"是两回事：
> mtp 没有 Meizu 的面板/TE/触摸/功放拓扑，`-inf` 有。

### 2.5 证据 4：v2/v3 的重建声明（这就是"搓"的核心动作）

提交 `a67869655`（v2，2026-10-03）：

```
m2381 DTS factory-first 重建 v2：整文件按原厂 corpus 重写（reset 205→133、
供电三轨改 GPIO 门控 vddio=pm8550gpio11/vdd=pm8550b gpio5/vci=pm8550gpio1、
micbias 全 1.8V、死 avdd 节点删除；逐段出处注释，台账同步）
```

提交 `2e12c6213`（v3，同日 40 分钟后）：

```
m2381 DTS factory-first 重建 v3：白名单制从头重建（v2 f42a93ef 降级对照基线）
——三审计后净 delta 13 项：cs35l45 中断线补齐(RCV=88/SPK=63)、va-micb 门控轨
新增(TLMM gpio0)、RPMH 八组逐轨取 RT 值(75 轨对账,8 轨实体差含 l6n 3.3V)、
adspslpi 0x6080000 对齐 base、va-dmic 600kHz、无证出局(haptics 死节点/ldo13/
sdam_9d00/eusb2-tune/camss→注释桩)；逐行出处注释，台账 v3 同步
```

现文件头（v3 声明，**这段是整个方法论的纲领**）：

```dts
 * factory-first 重建 v3（2026-10-04，DT 原厂化会话③）——白名单制从头重建：
 * 本文件不继承任何 inf（Meizu 20 Infinity）派生内容；每节点/属性持证上岗
 * （原厂出处 = corpus 三源之一，或主线 binding 必然性），v2（f42a93ef）降级为
 * 对照基线。逐行出处与分类 = meizu20-m1/dts/factory-first/LEDGER.md（台账，
 * 常驻维护——改此文件必须同步改台账）；前置审计 =
 * meizu20-m1/dts/factory-first/reports/AUDIT-T4-20261004.md（音频分片/RPMH
 * 轨族/reserved-memory 三对账，本文件的修正值全部出自该审计）。
 *
 * 原厂真值源（corpus，SHA256 固化在 corpus/SHA256SUMS）：
 *   base   = vendor_boot dtb 段 base DTB（corpus/vboot_a.fdt0.dts）
 *   entry9 = dtbo entry9 overlay（本机生效条目，board-id 0x1 0xf）
 *   RT     = runtime FDT（ABL 加工后地面真值，deepseek-round2-materials/）
 * 缩写：base/entry9/RT 同上；主线 = linux-mobile-ports 树 binding/dtsi 惯例。
```

---

## 3. 问题 2：怎么判定"这个节点该不该启用、这个 GPIO/regulator/时钟是什么值"

### 3.1 五条取证通道（按实际使用频次排序）

我统计了现 DTS（2,046 行 / 64,866 B）注释里的出处词频，用来估计各通道的"占比"（这是**词频估算**，
不是他自报的统计）：`RT` 104 次、`主线` 60 次、`stock` 47 次、`entry9` 21 次、`base` 17 次、
`实测` 8 次、`设备日` 9 次；结构化标签 `【A …` 48、`【D …` 21、`【B …` 2、`【RT …` 45。

| # | 通道 | 具体做法 | DTS 里的典型例子（原文） |
|---|---|---|---|
| ① **原厂 DT 三源**（占比最高，估 55~60%） | `base`（vendor_boot 的 DTB 段，dtc 反编译）定"板上有什么"；`entry9`（本机生效 dtbo overlay）定"面板/触摸/相机的本机参数"；`RT`（Android 跑起来后 `/sys/firmware/fdt`）定"ABL 加工后的最终值" | 见下 3.2 三个例子 |
| ② **主线 binding/dtsi 惯例 + 同 SoC 同外设板参照**（估 30%） | 凡是"驱动必需但原厂 DT 不表达"的（如 PMIC 间 `vdd-lX-supply` 链、`regulator-initial-mode`），按主线 sm8550 全系板同形补；同外设参照板上 `sm8550-hdk.dts`、`sm8550-mtp`、Sony `pdx234`(SM8550+Xperia)、"yodo"、"sheng"树 | `/* 【A：RT va-macro …】 */`、`/* PMIC 间 supply 链 …= 主线 binding 必需；拓扑取 QCOM 官方参考设计惯例（主线 sm8550 全系板同形），RT（RPMh 固件域）不表达 */`；`reset-gpios … 双 amp 共享声明 = 主线 yodo/pdx234（SM8550+CS35L45 活体）同款` |
| ③ **Android/Flyme 活体取证**（估 8~10%） | root 下 `i2cdetect`、`/sys/bus/i2c/devices/*`、`i2cget` 读 CHIPID、`tinymix`、`dmesg`、`debugfs`、`/proc/device-tree`；Flyme"取证日"专门开窗口做只读取证 | fsa4480：`i2cdetect 0x42 干净`；震动：`r55 实测真身 = AW8697（reg 0x00=0x97）`；触摸：`stock = humu L9B ~2.96V`；相机：`相机 ACK 真值 s5k3p9sx id 0x3109 @0x5a` |
| ④ **上机单变量 A/B**（估 5~8%） | 一个变量一轮，判据=固定次数复现（5/5、6/6）+ 寄存器/日志 marker | CS35L45 reset 极性（T4→T4b→T4c 三连）、haptics reset 极性（r56）、`qcom,panel-phy-timings` byte 量纲（T-TC） |
| ⑤ **原理图** | **未见任何证据**。全文件零"原理图/网络名/页码"引用；轨身份全部由 RT 的 regulator phandle（如 `0x2f4`）反解，而非看图 | `【A：RT wcd938x-codec 供电面：buck/rxtx/vddio 三轨全 = 0x2f4 = L15B …（AUDIT-T4 §1.2 轨身份解案）】` |

> 说明：他没有这台机器的原理图（否则不会用"轨 id 反解"这种绕法），也没有完整的下游 kernel DTS——
> 只有"vendor_boot 里那份 base DTB + dtbo 一条 overlay + 跑起来的 FDT"。这三样就是他的全部"图纸"。

### 3.2 三个"教科书级"判定实例（原文摘录）

**(a) 某个芯片到底焊没焊 —— fsa4480 的四重证据**

```dts
/*
 * port@2 (SBU/aux) removed 【D：fsa4480 摘除，10-07】：
 * 板上未焊 fsa4480（i2cdetect 0x42 干净 + flyme 取证日
 * 四重证据），节点在 -> 驱动 probe -ENODEV ->
 * pmic_glink_altmode EPROBE_DEFER -> typec port 永不注册。
 * SBU 无 mux 路由 = stock 同形态（typec 栈全活无 fsa4480）。
 */
```
配套提交 `ed8e7e494` 的正文把机理写全了：
`fsa4480: chip not on board (i2cdetect bus5 0x42 clean; flyme forensics day: stock typec stack fully
alive without it). Node present -> driver probe -ENODEV -> pmic_glink_altmode EPROBE_DEFER -> typec
port never registers. Remove typec-mux@42 + connector port@2 SBU endpoint … Retimer (nb7vpq904m)
stays: real SS-path hardware, stock-side confirmed.`

**方法论要点**：不是"DT 里有就抄"，而是"**DT 里有 ≠ 板上有**"；两条独立证据（I2C 探测 + 原厂同功能栈
在不含该芯片时仍全活）才允许删节点。删节点本身是**为了修一个链式失败**（EPROBE_DEFER 拖死 typec port）。

**(b) 一个 regulator 轨的"身份"——用 RT 的 phandle 反解**

```dts
/* 【A：RT eusb2-repeater@fd00 vdd18=0x2f4=L15B / vdd3=0x2ed=L5B（AUDIT-T4
 * §4 轨身份解案）。RT 的 tune = qcom,param-override-seq 下游形态（寄存器
 * 序列在 AUDIT-T4 §4 备查），主线四属性无直接映射证 ⇒ 不写入】 */
&pm8550b_eusb2_repeater {
	vdd18-supply = <&vreg_l15b_1p8>;
	vdd3-supply = <&vreg_l5b_3p1>;
};
```
**要点**：下游 DT 的 supply 是 phandle 数字（`0x2f4`），主线要的是节点引用 ⇒ 必须先把
"phandle → PMIC → LDO 编号"这张表建出来（这就是 AUDIT-T4 §2"75 轨对账"干的事）。
同时**证不出来的不写**：`qcom,param-override-seq` 那种下游私有 tune 序列，因为没有主线映射证据，
明确"不写入"。

**(c) 一个 GPIO 的"该高还是该低"——三连实验才定案**

`cs35l45_rcv` 的 reset 线，三个提交讲完一个完整判决链：

```dts
/* 【T4c(2026-10-04 设备日二迭代)：reset-gpios tlmm108 GPIO_ACTIVE_HIGH，
 * 双 amp 共享声明 = 主线 yodo/pdx234（SM8550+CS35L45 活体）同款；
 * 共享靠框架 -EBUSY 仲裁（第二实例 dev_dbg "shared reset" 直接 poll）。
 * 证据链：板上真值 = 物理高芯片活（T2 gpio108 high 双 probe 过 +
 * T4 boot @31 被 @30 err 路径放出来后 5ms 内 boot done）；主线
 * cs35l45.c 把 active 当出复位用（probe set_value(1)）→ 必须配
 * ACTIVE_HIGH。T4 的 stock flags 0x01=ACTIVE_LOW 是 vendored 驱动
 * 标准脉冲语义，跨驱动照抄 = set_value(1) 把芯片按进复位 = @30
 * OTP poll 5ms 超时（设备日实锤）。T4b 摘线判负 = 上电默认态
 * 线浮空芯片不复位自举，双 amp 全 timeout——必须有人驱动。】 */
```
**要点**：**"原厂 flags 值"和"主线驱动语义"是两个坐标系**。原厂 `ACTIVE_LOW(0x01)` 是给下游驱动
"打脉冲"用的；主线驱动把 active 当"出复位"用 ⇒ 照抄原厂 = 反向。判决靠"物理高时 ID 可读"这种
**不依赖驱动的硬事实**（T2 双 probe 通过），而不是靠读 DT。

**(d) 一个内存区该不该信 base —— 一次上机死亡换来的教训**

```dts
/*
 * adspslpi：v3 首上机（2026-10-04）实证 **0x6080000（base 值）
 * 致死**——remoteproc_adsp memory-region = adspslpi_mem（主线 pas
 * 把此区交给 meizu 12.6 DSP fw），fw 对区尺寸有硬合约：96.5MB 下
 * DSP 侧初始化卡死 ⇒ qrtr 零服务注册 ⇒ fastrpc/传感器链全灭。
 * 回退主线 dtsi 值 0x4080000（r19 传感器全绿/A3 批 20+ 天实跑值）。
 * **教训入册**：remoteproc memory-region = 固件合约面，factory-first
 * 不适用于此（base 的 Android 下游 fw 布局与主线 pas 载入不同栈）。
 */
```
**要点**：这是"factory-first（一切照原厂）"唯一被自己否掉的类目——**固件合约面不适用**。
这条对任何"照抄原厂 DT"的移植都成立（见 §8）。

### 3.3 占比结论（他怎么分配精力）

- **值（voltage/GPIO/reg/中断号）几乎全来自 corpus**：RPMH 八组 75 轨全部按 RT 逐轨写，
  只有 8 轨"实体差异"取了 RT、其余取主线范围；`reserved-memory` 与 base 全表对账。
- **拓扑（哪个 supply 挂哪个父轨、哪个 dai-link 连哪个 codec）来自主线 binding + 同外设参照板**，
  因为 RT 的 RPMh 固件域根本不表达这层。
- **"启不启用"来自实测 + 失败机理**：DP0 关了（deferred 拖死 DRM）、WSA macro 关（无器件）、
  WCD938x 关（SWR slave init 不完 → card -110）、fsa4480 删（未焊）。
- **纯"推断"被显式禁掉**：证不出来的节点一律降级成**注释桩**（相机注释块 30 行、震动桩 11 行），
  桩里只写"判源"，不写实体节点。

---

## 4. 问题 3：LEDGER 台账的格式与工作流

### 4.1 先说实话

`LEDGER.md` **本体取不到**（私有仓）。但它的**分类体系、书写粒度、更新纪律**可以从 DTS 反推得很清楚，
因为 DTS 里每个注释块就是台账行的"投影"。下面给出**有证据的部分**与**反推的样例格式**（标明）。

### 4.2 有证据的部分

1. **位置与强制同步**（文件头）：
   `逐行出处与分类 = meizu20-m1/dts/factory-first/LEDGER.md（台账，常驻维护——改此文件必须同步改台账）`
   ⇒ 台账是"改 DTS 必须同轮改"的**强耦合件**，不是事后文档。
   多份提交信息末尾都写"台账同步 / LEDGER §6 同步 / 台账 v3 同步"（见 `c8b1b958b`、`a67869655`、`2e12c6213`）。
2. **分类轴 = 出处**，共四类（从标签语义与用法反解，全部有原文佐证）：
   - `【A：…】` = **原厂 corpus（Attested）**，必带具体源与节点/属性名，48 处。
     例：`【A：base chipinfo_region@81cf4000 0x1000 no-map；主线缺此项】`
   - `【B：…】`（含 `【A/B】`）= **主线 binding 必然性**，2 处显式 + 多处文字形式。
     例：`【B：DSI 主时钟轨=下游不映射（RPMh 固件域），主线 binding 必需；l3e 1.2V = RT ldoe3 实值 1200/1200 自洽】`
   - `【D：…】` = **自主判决/战役产物（Deliberate）**，21 处，必须写"为什么必须这么干 + 谁定的"。
     例：`【D：功耗战役产物（wls-tx 幻影风暴根除，9-30）；stock 树无此概念】`
   - `【RT xxx】` = **逐项原值抄录**（regulator 轨这种"75 条"的量），45 处。
     例：`/* 【RT ldon6 3304/3304 init 3304（v2 2800——实体差 2.8→3.3V，取 RT；消费面=相机/传感族未启用）】 */`
   - 另有**轮次标签**：`【T4(2026-10-04)：…】`（7 处）、`【录音轮 A0(2026-10-06)：…】`、`【相机第 6 轮 R1(2026-10-06)：…】`、
     `【（七十五）…】` —— 表示"这条是第几轮设备日/哪个审计改的"，可回溯到实验日志编号。
3. **台账必须写"反例"**：如 `L13B（旧面板 vci LDO）RT=disabled——三轨 GPIO 门控改法的 stock 自刀实证`、
   `RT 缺轨（ldob1/4/10、ldog2、ldom6）无主线消费者，不写入`。
   ⇒ 台账不只记"写了什么"，还记"**为什么没写**"。

### 4.3 反推的台账行格式（`【推断】`，仅为可照做的复刻样例）

按上证据，一个可复刻的 `LEDGER.md` 行至少要有 6 列：

| 字段 | 样例 |
|---|---|
| DTS 定位 | `&pm8550b_eusb2_repeater / vdd18-supply` |
| 值 | `<&vreg_l15b_1p8>` |
| 分类 | `A`（原厂） |
| 出处 | `RT eusb2-repeater@fd00 vdd18=0x2f4=L15B；AUDIT-T4 §4` |
| 判定/存疑 | `tune(qcom,param-override-seq) 无主线映射证 ⇒ 不写入` |
| 轮次/日期 | `factory-first v3 / 2026-10-04` |

对应的 Markdown 行（建议形态）：
```
| dts:1307 | &pm8550b_eusb2_repeater.vdd18-supply | A | RT 0x2f4=L15B（AUDIT-T4 §4） | — | v3 2026-10-04 |
| dts:1352 | &usb_dp_qmpphy.mode-switch | D | 主线 typec 栈形态（不进 orientation-switch） | 反面：orientation 由 pmic-glink 管 | 10-06 |
```

### 4.4 另一本"真台账"（这个是公开的，可直接照抄格式）

`Mu-Silicium/Platforms/Meizu/m2381Pkg/FdtBlob/Source.txt` 是**交付链台账**：每轮一行块，记录
`fork commit / dtb sha8 / dtb 字节数 / apk pkgrel / 内核 #N / Mu 镜像名 / ESP 版本 / 判决`。原文节选：

```
T-TC round 2026-10-04: fork 377e4d3256ae dtb 108a0a5e (qcom,panel-phy-timings
byte-scale) was baked in as f9808c21, built as mu-ttc-3fe4ecb0.img, flashed
and JUDGED NEGATIVE — true-sleep wake snowflake 5/5 same structure as
bitclk/E4 rounds. TC0-13 eliminated. Rolled back to v3b this commit.
...
r55 mini round 2026-10-04 (device day, user calls S2=15 + haptics now): fork
2d88f9ac6236 dtb 78cc13e6 (136,352B; +&i2c_hub_5 enable + haptics@5a
awinic,aw86927; panel BL_MIN 50->15 in kernel .c). linux-meizu-meizu20 r55;
kernel #56.
```

> 这本台账的写法值得直接照搬：**"授权源 → dtb sha → 字节数 → 包版本 → 上机号 → 判词"** 一条链，
> 任何时候都能回答"现在机上跑的那份 DTS 到底是哪一版、判过没有"。

---

## 5. 问题 4：AUDIT-T4 审计做了什么

### 5.1 定位与结构（由 DTS 的 15 处引用反推）

- 文件名 `AUDIT-T4-20261004.md`，日期 2026-10-04，是 v3 重建的**前置审计**：
  `前置审计 = …/reports/AUDIT-T4-20261004.md（音频分片/RPMH 轨族/reserved-memory 三对账，本文件的修正值全部出自该审计）`
- 章节骨架（被引用到的）：
  - **§1 音频分片**：§1.1 实体差异、§1.2 轨身份解案、§1.3 C 类（下游形态差）、§1.4 VA/DMIC
  - **§2 RPMH 轨位族**：§2.1~§2.3（含 "§2.3 = L13B stock 自刀 disabled"）、"§2 对账 75 轨"
  - **§3 reserved-memory 全表对账**
  - **§4 轨身份/杂项解案**：eusb2 双轨身份、`tlmm gpio-reserved` 改判、eusb2 tune 不可写
- 产出形态：**"净 delta 13 项"**（v3 提交信息），即审计完只允许 13 处改动落地，其余"无证出局"。

### 5.2 三个"对账"各自解决了什么

**(1) 音频分片（§1）——把"抄来的音频"变成"本机音频"**

| 审计点 | 结论（DTS 原文） |
|---|---|
| 功放是谁 | `RT cs35l45@30=dsp-part-name cs35l45-rcv / @31=cs35l45-spk（扬/听筒 = SEC MI2S，战役三源实锤）` |
| 中断线 | `★v3 新增（AUDIT-T4 §1.1 实体差异搬入）：中断线 RCV=gpio88 / SPK=gpio63 LEVEL_HIGH` |
| WCD 供电三轨身份 | `【A：RT wcd938x-codec 供电面：buck/rxtx/vddio 三轨全 = 0x2f4 = L15B 1.8V、mic-bias = 0x2f7 = BOB1（AUDIT-T4 §1.2 轨身份解案）】` |
| SWR 端口映射 | `端口映射主线形 1-5/2,2,3,4（RT 下游 num-ports 12/5 + is-always-on 差异 = AUDIT-T4 §1.3 C 类…）` |
| VA 麦克风 | `【A：RT va-macro qcom,va-dmic-sample-rate = 0x927c0 = 600000（AUDIT-T4 §1.4，v2 的 4800000 为 inf 偏差）】`、`vdd-micb = TLMM gpio0 门控轨` |

⇒ 音频分片的实质：**把 v2 里"从 Inf 抄来的 4.8 MHz DMIC 采样率、缺失的功放中断线、缺的 va-micb 门控"
按 RT 逐项纠正**，并把"下游 C 类差异"（SWR 端口数、always-on）只入册、不改主线形态。

**(2) RPMH 轨位族（§2）——75 轨逐轨对账**

DTS 顶部有整段审计结论（原文）：

```dts
/*
 * RPMH 轨位族【v3 逐轨按 RT 值重建（AUDIT-T4 §2 对账 75 轨）：
 * - 实体差异 8 轨取 RT 值：bob1 min 3008 / bob2 2704-3008 / l7b max 3008 /
 *   l11b min 1200 / l1g 1144-1256 / l7m 2800-2904 / l2n 1104 / l6n 3304
 * - RT 缺轨（ldob1/4/10、ldog2、ldom6）无主线消费者，不写入
 * - initial-mode = HPM（RT init-mode 0x04 = downstream HPM；特例 smpg4
 *   RT init=retention，运行态 HPM 保留 + 台账注记）
 * - PMIC 间 supply 链（vdd-lX-supply 族）= 主线 binding 必需；拓扑取 QCOM
 *   官方参考设计惯例（主线 sm8550 全系板同形），RT（RPMh 固件域）不表达
 * - L13B（旧面板 vci LDO）RT=disabled——三轨 GPIO 门控改法的 stock 自刀实证
 */
```
⇒ 这段是全 DTS 信息密度最高的地方：**"取 RT / 不写 / 取主线惯例 / 特例注记"四种处置的分类规则**，
可直接拿去当任何 SM8550 机型 RPMH 段的施工规范。

**(3) reserved-memory（§3）——三源全表对账**

```dts
	/*
	 * 板级补充项（主线 sm8550.dtsi 自带表与 base 同源，AUDIT-T4 §3
	 * 全表对账）：chipinfo/llcc_lpi = base 有而主线缺；hwfence-shbuf
	 * 主线 0x279000 < base 0x2dd000；adspslpi = 固件合约面，保持主线值
	 * （0x6080000 上机实证致死，见下方节点注）；rmtfs/splash/ramoops =
	 * 我方实跑锚/战役产物；adsp_rpc_remote_heap = base 同尺寸 12MB。
	 */
```
⇒ 四类处置：**base 有主线缺 → 补；两源尺寸不一致 → 取大（base）；固件合约 → 取主线；都没有 → 自建并标 D**。

**(4) §4 的两个小解案**（也很能说明"审计粒度"）

- `tlmm gpio-reserved-ranges = <32 8>` 的**改判**：
  `【A：RT tlmm qcom,gpios-reserved = 32..39 = <32 8>（下游形态同值；v2 注释「stock 无声明」系误判，本行改判 A——AUDIT-T4 §4）】`
  ⇒ 审计会**推翻自己上一版台账的分类**（D→A），并留痕"系误判"。
- eusb2 tune 序列：`主线四属性无直接映射证 ⇒ 不写入`（见 §3.2b）。

### 5.3 AUDIT 与 LEDGER 的关系

`AUDIT-T4` 是**一次性、可归档的"审计报告"**（发现问题 → 给修正值）；`LEDGER` 是**常驻的"逐行户口本"**
（每个值现在归哪一类）。工作流是：**审计产出 delta → 落 DTS → 台账同步分类 → 提交信息写"净 delta N 项"**。
这三件事在同一轮里闭环，DTS 头注释同时钉住两份文档的路径。

---

## 6. 问题 5：一共迭代了多少轮、每轮判据是什么

### 6.1 数量

- **只改 DTS 文件的提交：25 条**（2026-09-29 → 2026-10-07，API `commits?path=…/sm8550-meizu-20.dts`）。
- 其中**整文件级重建 3 次**（v1 导入 / v2 corpus 重写 / v3 白名单重建）+ 1 次回退（v3b）。
- 之后按"设备日轮"推进，DTS 与驱动/内核同轮，轮次编号 `r55 / r56 / r57 / r60 / r62 / r67 / r68 / r69`，
  另有专项轮 `T1 / T4 / T4b / T4c / A0（录音）/ R1（相机）/ E4 / T-TC / T2`。
- 交付链台账 `Source.txt` 里**明确记录的 DTB 版本 = 8 个**（含 1 个判负回退的 `mu-ttc-3fe4ecb0.img`）；
  而未进台账的中间态还有若干（台账自己注明 `r67/r68 当时未入库=欠账于此一并补齐`）。

### 6.2 轮次阶梯与判据（关键 12 轮）

| 轮 | 日期 | 改了什么 | 判据 / 判词 |
|---|---|---|---|
| v1 导入 `27be20775` | 09-29 | 从 silime `-inf.dts` 拷骨架，改 model/compatible、真 `/memory`、去 stdout-path、触摸 1080×2400、`te-source=mdp_vsync_p` | 能起内核（"true /memory, no stdout-path" 三条都是 bring-up 必需） |
| 清残留 ×4（`7a693447b`/`f012c798b`/`f3fee562e`/`9caa67ec6`） | 09-30 | 删 IMX563 相机块、关无线充、删 DP0 dai-link、接 CS35L45 双功放 | "drop inert inf leftovers **found by DTB audit**"——先做**DTB 级静态审计**再上机 |
| v2 `a67869655` | 10-03 | 整文件按 corpus 重写：reset 205→133、三轨改 GPIO 门控、micbias 全 1.8V | 原厂逐段比对（"逐段出处注释"） |
| v3 `2e12c6213` | 10-03 | 白名单重建，三审计后净 delta 13 项 | 审计准入制（无证 → 注释桩） |
| v3b `3e7c32e37` | 10-03 | `adspslpi` 0x6080000 → 0x4080000 | **上机致死判负**：DSP 初始化卡死→qrtr 零注册→传感器链灭 |
| 花屏 E4 + T-TC `90739a5fc` | 10-03 | reset 10/10/10ms 对齐 stock；`qcom,panel-phy-timings` u8[14] 灌 RT 原值 | **`真睡唤醒 5/5 全花`** ⇒ 判负（`TC0-13 eliminated`） |
| prep 轮 `8f19bcd9c` | 10-03 | iris firmware-name、NFC@0x28 落地、haptics 桩升真身 | 编证 `cpp+dtc 绿 136,216B`；"上机挂设备轮" |
| r55 `c8b1b958b` | 10-04 | `i2c_hub_5` 使能 + `haptics@5a`；面板 BL_MIN 50→15 | "判型与落地合并一轮"（994000 不使能则无法判型） |
| r56 `c4cf3b04b` | 10-04 | haptics reset `ACTIVE_HIGH→ACTIVE_LOW` | **物理低=芯片活（ID 可读）/ 物理高=总线全静默** ⇒ 极性定案；同时读出真身 AW8697 |
| T4 `1055d3955` | 10-04 | 摘 WCD dai-link ×2、wcd938x/swr1/swr2 disabled（对齐 stock） | 判读设计："SPK 出声 = 宏/DSP/MI2S 链全通 ⇒ 问题收敛 WCD SWR TX"；编证 `135,782B`（基线 136,352 B，delta=WCD 摘除量，警告 17=17） |
| T4b → T4c `21345209e` → `8173f023e` | 10-04 | 先"摘 reset 线"→ 判负；改"双 amp 共享 reset ACTIVE_HIGH" | T4b：**双 amp 全 timeout ⇒ 线浮空芯片不复位自举，必须有人驱动**；T4c：boot 后 5ms 出声 |
| fsa4480 摘除 `ed8e7e494` | 10-06 | 删 `typec-mux@42` + connector `port@2`；同时撤 pm8008 扫描轮 14 条 always-on | **i2cdetect bus5 0x42 干净 + 原厂栈无该芯片仍全活** ⇒ typec port0 点亮 |
| ramoops 搬位 `39d23ba8b` | 10-07 | `0xa5100000 → 0xa8000000` | 原址落在 Mu 内存图 Display Demura 区（每 boot 覆写）⇒ "六死零现场"；搬到 Mu「Kernel」Reserv 洞 |

### 6.3 判据的"语法"

他的判据不是"看起来好了"，而是三类可复现量：

1. **重复次数**：`5/5`、`6/6`（真睡唤醒花屏、knob 归零臂）。文档里甚至写明"×5 协议按判负提前锁死"。
2. **一个唯一 marker**：`dsi_err status=4 每轮一条 = 链路真断 marker`；`卡 -110`、`EPROBE_DEFER`、
   `OTP poll 5ms 超时`、`REG 0x00=0x97`、`ACK id 0x3109`。
3. **字节/尺寸守恒**：`cpp+dtc 绿 135,782B（基线 136,352B，delta = WCD 摘除量；警告同族 17=17）`、
   `dtb sha8 = xxxx`、`verify.sh` 五项对拍、上机 `uname -v = #N = pkgrel+1`、`dd` 读回 sha。

> 这三类判据的组合是他能"一天十几轮"还不乱的根本原因：每轮都有**一个数字**说"变了/没变"。

---

## 7. 问题 6：从零到能开机的完整步骤清单（可复用）

> 说明：**标 ✅ 的有公开证据**（脚本/文档原文）；标 `【复现配方】` 的是我按证据补全的命令形态
> （他没公开逐条命令行，但用到的通道与产物名在 DTS / 文档里都有）。顺序按真实依赖排。

### 阶段 A：素材与备份（动手前）

1. ✅ **先有 EDL/9008 全分区备份**（`BOOT-CHAIN-RE.md` §7.1：`前提：可解锁的设备 + 一次完整备份`）。
2. ✅ **确认代次**：`BOOT-CHAIN-RE.md` §7.1 明确"本文地址表对 Flyme 12.6（Android 16，BQ2A.251016.001）
   user 变体成立……其他固件代次/变体**地址会漂移**"。⇒ 记录 `ro.build.display.id` / bootloader 版本。
3. ✅ **红线**：只碰 `boot_b / recovery_a / userdata`；`xbl/abl/tz/modem/dtbo_b/super/modemst/persist` 永不碰
   （`DESIGN.md` §1.1、`FLASHING.md` §8）。

### 阶段 B：建 corpus（三源）

4. ✅ **base DTB**：从 `vendor_boot` 的 dtb 段取 → `corpus/vboot_a.fdt0.dts`（DTS 头已点名文件名与来源）。
   `【复现配方】`
   ```bash
   adb shell su -c 'dd if=/dev/block/by-name/vendor_boot of=/sdcard/vb.img'
   adb pull /sdcard/vb.img
   unpack_bootimg --boot_img vb.img --out vb        # AOSP unpack_bootimg
   dtc -I dtb -O dts -o corpus/vboot_a.fdt0.dts vb/dtb
   ```
5. ✅ **entry9 overlay**：先读 `ro.boot.dtbo_idx`（本机 = **9**）与 board-id（`0x1 0xf`）确定"本机生效的那条"。
   DTS 头：`entry9 = dtbo entry9 overlay（本机生效条目，board-id 0x1 0xf）`；`BOOT-CHAIN-RE.md` §1.3 亦记
   `本机 ro.boot.dtbo_idx=9：goodix brl-d 触控 + BOE AMOLED cmd-mode DSC 面板`。
   `【复现配方】`：`dd dtbo_a/b` → 用 `mkdtboimg.py dump` 或按 DTBO header 拆表取第 9 条 → `dtc -I dtb -O dts`；
   需要合并视图时 `fdtoverlay -i base.dtb -i overlay9.dtb -o merged.dtb`
   （DTS 里引用了 `factory-first/corpus/merged.entry9.dts`，证明他做过合并视图）。
6. ✅ **RT（runtime FDT）**：Android 跑起来时 `cat /sys/firmware/fdt`（v1 文件头写明 `stock /sys/firmware/fdt,
   harvest 2026-09-21`）。这是**ABL 加工后的地面真值**，也是 `reserved-memory`/`/memory`/regulator phandle
   的唯一真值源。`【复现配方】`：`adb shell su -c 'cat /sys/firmware/fdt' > rt.fdt && dtc -I dtb -O dts -o rt.dts rt.fdt`；
   `dtc` 吃不下的用 `fdtdump` 兜底。
7. ✅ **SHA256 固化**：`corpus/SHA256SUMS`（DTS 头点名）——三源被哈希钉死，防止"换了固件还拿旧 DTS 说话"。

### 阶段 C：骨架 + 静态审计（还没上机）

8. ✅ **拿同厂兄弟机型参考 DTS**（本例：`silime/linux@7.3.0-dev: sm8550-meizu-20-inf.dts`），
   复制成 `sm8550-meizu-20.dts`，改 `model/compatible`，在 `Makefile` 加 `dtb-$(CONFIG_ARCH_QCOM) += sm8550-meizu-20.dtb`。
9. ✅ **先做静态 DTB 审计**（不上机）：`7a693447b` 的判词是 "found by **DTB audit**"，即把新 DTS 编出的 DTB
   与三源逐节点/逐属性比，列出"骨架里有、本机没有"的（IMX563 相机、无线充、DP0 dai-link）先删。
10. ✅ **白名单重建（factory-first）**：每个节点/属性必须能指向 `base/entry9/RT` 之一或主线 binding；
    指不出的**降级为注释桩**（桩里写判源与轮次），而不是删掉了事——因为"以后要回来"。
11. ✅ **编证**：`cpp + dtc` 编过 + **DTB 字节数对基线**。原文判据形如
    `编证：cpp+dtc 绿 135782B（HEAD 基线 136352B，delta=WCD 摘除量；警告同族 17=17）`。
    `【复现配方】`：`make ARCH=arm64 LLVM=1 qcom/sm8550-meizu-20.dtb`（或 `cpp -nostdinc -I include -I arch/arm64/boot/dts/qcom … | dtc -I dts -O dtb`），
    再用 `stat -c %s` 对比基线，并把 `dtc` 警告条数与基线比（"17=17"）。

### 阶段 D：构建与交付（DTS → 机上）

12. ✅ **内核 apk**：`script/build-kernel.sh --bump` = `git archive` 打 tarball → `pmbootstrap checksum` →
    `pmbootstrap build linux-meizu-meizu20 --force`；`KBUILD_BUILD_VERSION=$((pkgrel+1))` 实现 **#N = pkgrel+1** 定律。
    APKBUILD 必须 `make modules_install dtbs_install install`（**不打 zinstall**：Mu 链要裸 `Image`）。
13. ✅ **Mu（仅 DTS 变了才做）**：`script/build-mu.sh` = 从**同一个 apk** `tar -xzf … boot/dtbs/qcom/sm8550-meizu-20.dtb`
    → 覆盖 `Platforms/Meizu/m2381Pkg/FdtBlob/sm8550-meizu-20.dtb` → `.venv/bin/python build_uefi.py -d m2381 -r RELEASE`
    → 产物改名 `mu-r<PKGREL>-<sha8>.img`。同步更新 `Source.txt`（那本交付台账）。
14. ✅ **ESP**：`build-esp.sh` 从 apk 抽 `vmlinuz-efi` 灌进 100 MiB FAT32 的 `\EFI\BOOT\BOOTAA64.EFI`。
15. ✅ **verify.sh 全绿才算数**：①apk 内 DTB ↔ Mu FdtBlob **sha256 同源**；②tarball 扫 `-inf` 残留 + `model="MEIZU20"` +
    binding yaml 新名；③`zram.ko/zsmalloc.ko/uinput.ko/uhid.ko/vmlinuz-efi` 在列；④ESP 内 `BOOTAA64.EFI` ↔ apk `vmlinuz-efi` 同源；
    ⑤打印期望 `uname #N`。
16. ✅ **刷写**：`fastboot flash boot_b mu-rNN.img` + `fastboot flash recovery_a esp.img` → `fastboot reboot`；
    成功后 `dd` 读回对 sha（`readback.sh`）——"刷写时长不算证据，只看 dd 读回"。
17. ✅ **首 boot 验收清单**（`FLASHING.md` §5）：
    ```bash
    uname -v                                   # ① #N = pkgrel+1
    cat /proc/asound/cards                     # ② 卡名 MEIZU20 注册
    ls /sys/class/backlight                    # ③ 背光在
    systemctl --failed                         # ④ 已知三件非回归才算通过
    journalctl -b | grep -iE "error|fail"      # ⑤ 无新红
    ```

### 阶段 E：逐外设推进（DTS 之外的"另一半"）

18. ✅ **外设顺序**（实际发生顺序，见 §6）：显示/面板 → UFS/输入 → typec/USB → WiFi+BT → 音频 → 传感器 → 震动 → NFC → 相机。
19. ✅ **每个外设的"启不启用"三问**（从 DTS 归纳）：
    ① 原厂 DT 里有实体节点吗（有值可抄）？② 原厂栈里它真的在工作吗（同功能链路是否依赖它）？
    ③ 主线驱动栈需要什么 parent（regulator/phandle/dai-link）才能 probe？
    三问缺一，就先落"注释桩 + 判源"，等设备日实测。
20. ✅ **单变量 A/B + 次数判据**：一轮只改一个变量，判据写死次数（5/5、6/6）与 marker，判负就 revert 并写进"排雷表"
    （例：`PANEL-CORRUPTION.md` §2 那张 13 行表，每行"嫌疑/实验/判决"）。

---

## 8. 这套方法能不能用到"另一台同 SoC 不同机型"？

**能，但要换三样东西、并记住两条禁令。**

### 8.1 可平移的部分（与方法强相关、与机型弱相关）

| 件 | 为什么可平移 |
|---|---|
| **corpus 三源法**（vendor_boot base DTB / 生效 dtbo entry / runtime FDT） | 高通 + Android 启动链的通用形态；魅族 21 Note 同样是 vendor_boot + dtbo，`ro.boot.dtbo_idx` 一样能读 |
| **白名单 + 注释桩** | 与机型无关，是"防抄错"的工程纪律 |
| **出处标签 + 台账 + 改 DTS 必须同步台账** | 纯流程，可直接照搬（§4.3 给了表结构） |
| **AUDIT 三对账**（音频分片 / RPMH 轨族 / reserved-memory） | 这三块是 SM8550 平台**共性**：PMIC 组（pm8550/pm8550b/pm8550ve/pm8550vs/pm8010/pmk8550）在绝大多数 kalama 机型上同构，75 轨表可整段复用**结构**，只需换值 |
| **判据语法**（5/5、唯一 marker、字节守恒、#N 定律、dd 读回） | 与机型无关 |
| **交付链纪律**（DTB 只从同一个 apk 抽、verify.sh sha 对拍、仅 DTS 变才重编 Mu） | 与机型无关；同 SoC 的 Mu 平台包可以复制 `m2381Pkg` 改 |

### 8.2 必须换掉的部分

1. **骨架**：不能再抄 `-inf.dts`（那是魅族 20 Infinity）。21 Note 需要自己的参考 DTS（同 SoC 的
   `sm8550-*` 主线板，或另一台已被社区 bring-up 的 kalama 机型），并且**抄骨架前先做静态 DTB 审计**。
2. **corpus 三源**：全部重做。**特别注意**：魅族 21 Note 的 dtbo entry 号、panel timing、触摸 IC、
   功放型号都可能与 m2381 不同（m2381 = BOE B5011A05 + goodix gt9916 + CS35L45×2；21 Note 需实测）。
3. **"固件合约面"的值**：见 8.3。

### 8.3 两条禁令（他用自己的失败换的，别重犯）

- **禁令 1：`remoteproc` 的 `memory-region` 不要照抄 base 值。**
  nura 把 `adspslpi` 改成 base 的 `0x6080000`（96.5 MB）⇒ DSP 初始化卡死 ⇒ qrtr 零注册 ⇒ 传感器链全灭，
  一轮就回退。原因写在 DTS 里：**"base 的 Android 下游 fw 布局与主线 pas 载入不同栈"**。
  ⇒ 同 SoC 新机型同样适用：**只要走主线 `remoteproc` + vendor 固件，就用主线 dtsi 的尺寸**。
- **禁令 2：原厂的 flags/极性不能跨驱动照抄。**
  `cs35l45` reset 的 `ACTIVE_LOW` 是给下游驱动"打脉冲"的语义；主线驱动把 active 当"出复位"用 ⇒ 照抄 = 反向。
  判据必须是**不依赖驱动的硬事实**（"物理高时 I2C ID 可读"）。

### 8.4 对"魅族 21 Note"的具体建议（结合本地 `移植记录_20261027*`）

- 你现在卡在"initcall 全跑完但 init 不执行 / 18 个节点缺失"——**这正是 corpus 缺失的典型症状**，
  不是 DTS 语法问题。按 §7 阶段 B 把三源建起来，`RT` 一拿到，`/memory`、`reserved-memory`、
  PMIC 轨、`/chosen` 的争议会一次性消掉一半。
- 你已解决 8 个 config 层问题（`earlycon=efifb`、`CONFIG_QCOM_WDT=y`、UFS/I2C/PHY 全 `=y`）——
  这些属于**阶段 D 的"能出日志"**，与 nura 的 `earlycon=efifb` + fbcon 决策同构（他也**故意删掉
  `chosen/stdout-path`**，让 console 走 fbcon：`【D：UEFI 链控制台形态（R23bi 定案）】`）。
- 他的 DTS 里 `chosen {}` 是**空的**并有 8 行注释解释为什么——这一条你大概率可以直接照抄结论。
- 建议直接复刻他的产物链：`verify.sh` 的 5 项对拍 + `Source.txt` 台账格式 + `#N=pkgrel+1` 上机验证点。
  这三件能把你现在"改了不知道哪版在机上"的混乱一次性消掉。

### 8.5 不可平移的"隐形资产"

他的效率大头其实在**私有工作区**：`experiment-log.md`（九十多轮叙事）、`AGENTS.md`（硬定律/坑册）、
`corpus/`、`LEDGER.md`、`AUDIT-T4`。这些**没有公开**，所以"照抄方法"能拿到流程，拿不到他那几十次
试错的"结论库"。⇒ 对你自己项目的启示：**从第一天就把台账/实验日志当交付物建起来**，否则半年后
你只有一份 DTS，没有"为什么"。

---

## 9. 取不到的文件（再次明确，未编造）

| 路径（DTS 内引用） | 取不到的原因 |
|---|---|
| `meizu20-m1/dts/factory-first/LEDGER.md` | 私有工作区；四个公开仓 tree 中不存在 |
| `meizu20-m1/dts/factory-first/reports/AUDIT-T4-20261004.md` | 同上 |
| `…/reports/PANEL-GROUND-TRUTH.md` | 同上 |
| `…/corpus/{SHA256SUMS, vboot_a.fdt0.dts, merged.entry9.dts}` | 同上（且含原厂提取件，作者政策"stock 提取件零入仓"） |
| `deepseek-round2-materials/`（RT 素材） | 同上 |
| `pmos_linux` 私有仓 `AGENTS.md`、`docs/meizu20/experiment-log.md` | 无远端 |

本报告对以上内容的描述**全部来自**：DTS 内嵌注释（15 处 AUDIT-T4 引用、48 处 A 标签、45 处 RT 标签）、
`FdtBlob/Source.txt`（12 轮交付台账）、25 条 DTS 提交信息、以及公开 docs 六篇。凡越过这三类证据的，
均已标注 `【推断】`/`【复现配方】`。

---

## 10. 证据文件索引（本机已落盘，可复查）

```
$LOCALAPPDATA/Temp/nura/
  sm8550-meizu-20.dts                     # 2046 行，主证据
  dts_v1.dts                              # 从 27be20775.patch 还原的 v1（1776 行）
  silime_inf_7.3.0-dev.dts                # 骨架原件 45,692 B
  diff_inf_vs_v1.txt                      # 骨架 vs v1 的 diff（3870 行）
  27be20775.patch / a67869655.patch / 2e12c6213.patch / ed8e7e494.patch
  pmap_linux_APKBUILD                     # silime 血统原文
  pmap_device_APKBUILD                    # 用户态契约（34 KB 注释）
  mu_Source.txt                           # 交付链台账（12 轮）
  AGENTS.md, docs_{DESIGN,PIPELINE,BOOT-CHAIN-RE,AUDIO-METHOD,PANEL-CORRUPTION,SUSPEND-S2IDLE}.md
  docs_FLASHING.md, script_{build-kernel,build-mu,verify}.sh
$LOCALAPPDATA/Temp/c_dts.json             # 25 条 DTS 提交（含正文）
$LOCALAPPDATA/Temp/tree_nura.json / tree_pma.json / tree_mu2.json
```
