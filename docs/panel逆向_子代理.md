# 魅族 21 Note（m2468 / SM8550）面板逆向：DSI 初始化序列提取 + 「最小假 panel」可行性

- 对象：原厂 `/vendor/lib/modules/msm_drm.ko`（5,660,472 B，aarch64 REL，not stripped）
- 面板：`ILI7838E_TIANMA_MEIZU`，1264×2780，DSC cmd mode AMOLED
- 工具环境：WSL Ubuntu，`python3` + `readelf`/`objdump`/`aarch64-linux-gnu-objdump` + `dtc`
- 内核对侧：`/home/shrp/lmp73`（Linux 7.3.0，已完整编译，`vmlinux`/`Image` = 2026-10-29 00:57）
- 全程只读分析：**未修改内核源码、未刷机、未连接手机**

---

## 0. 结论（先看这里）

| 项 | 结果 | 一句话 |
|---|---|---|
| **任务 A：从 msm_drm.ko 提取面板初始化序列** | ⚠️ **在 ko 里不存在，改道 dtbo 后完全成功** | ko 里没有静态 `dsi_cmd_desc` 数组；命令由 `qcom,mdss-dsi-on-command` DT 属性驱动。原厂 dtbo 里 5 档时序全部解出（84/84/84/100/98 条命令） |
| **任务 B：假 panel 能否建出 card0** | ✅ **能，而且大概率不用写新驱动** | 现场 DTS 的 `panel@0` 节点和 endpoint 早就接好了，`compatible` 也和树里的 `panel-boe-meizu20.c` 完全匹配——只是 `CONFIG_DRM_PANEL_BOE_MEIZU20` 没使能，驱动根本没编进内核 |
| 最大不确定性 | 见 §2.7 | `dsi_mgr_bridge_mode_valid` 的 OPP/时钟检查会不会把 mode 判掉；以及真面板是 cmd mode + DSC，video mode 只是脚手架 |

**最短路径建议（10 分钟级）**：先把 `CONFIG_DRM_PANEL_BOE_MEIZU20=y`，重建内核，看 `/dev/dri/card0` 是否出现。出现 = 判完任务 B 的可行性；再换假 panel / 真 ili7838e 驱动调画面。

---

## 1. 任务 A：DSI 初始化序列

### 1.1 ELF 结构

```
ELF 64-bit LSB relocatable, ARM aarch64, not stripped
BuildID 18293a2de008d8e00b1c16357c8f392d61999064
88 个节头，.shstrtab 在 idx 86
```

关键节（`readelf -S -W` 实测）：

| 节 | off | size | 说明 |
|---|---|---|---|
| `.data` | 0x00a820 | 0x017f30 | 可写数据 |
| `.rodata` | 0x022750 | 0x075830 | 只读，flags = `AMS`（含 SHF_MERGE\|SHF_STRINGS） |
| `.text` | 0x098000 | 0x1944a8 | 代码，4K 对齐 |
| `.symtab` | 0x049bc30 | 0x07b030 | **20,994 个符号（5,478 FUNC / 850 OBJECT）** |
| `.rela.text.__cfi_check_fail` | 0x023b628 | 0x20b338 | 实际作用于 `.text`（sh_info=9）的全部重定位 |

> 提示：`.rela.text.__cfi_check_fail` 这个名字有误导性——它是 `.text` 的**唯一**重定位节（CFI 插桩后名字被改写），所有代码里对常量的引用都在这里。

### 1.2 定位字符串引用：绕开「无符号」的坑

面板名字符串在文件偏移 **0x4d86c** = `.rodata + 0x2b11c`：

```
0x4d86c: "ILI7838E_TIANMA_MEIZU\0"
  其后紧跟 "*ERROR* [msm-dsi-error]: [%s] failed to send DSI_CMD_SET_TIMING_SWITCH cmds, rc=%d"
  前后都是 dsi_panel.c 的通用日志——说明它是**运行时按名字比对**的常量，不是某个面板专有表的成员
```

坑：`.rodata` 带 `SHF_MERGE|SHF_STRINGS`，字符串合并后**没有独立符号**（`symtab` 里查不到 0x2b11c 的条目），也没有指向它的 `R_AARCH64_ABS64` 重定位。

解法：**在 `.text` 重定位表里按 addend 匹配**。aarch64 取字符串地址走 `ADRP + ADD` 两条指令：

- `R_AARCH64_ADR_PREL_PG_HI21` (type 275)
- `R_AARCH64_ADD_ABS_LO12_NC` (type 277)

两者的 `r_addend` 都等于 `0x2b11c`。扫描结果：**44 处命中，落在 22 个函数里**。

| 引用函数 | 起始地址 | 引用点 |
|---|---|---|
| `display_set_panel_hbm` | 0x06770c | 0x677d4 |
| `display_panel_hbm_off` | 0x06897c | 0x68aa0 |
| `display_panel_adfr_thread_init` | 0x06a14c | 0x6a174 |
| `display_panel_adfr_handle_idle_mode` | 0x06a204 | 0x6a284 |
| `display_panel_adfr_send_minfps_cmd` | 0x06a308 | 0x6a344 |
| `display_panel_adfr_dynamic_te_handler` | 0x06a72c | 0x6a79c |
| `display_panel_adfr_get_dynamic_te` | 0x06aa38 | 0x6aa78 |
| `display_panel_adfr_status_switch` | 0x06ad18 | 0x6ad40 |
| `display_panel_adfr_tactics` | 0x06ae0c | 0x6ae34 |
| `display_panel_status_reg_read` | 0x06ca58 | 0x6ca98 |
| `display_panel_local_hbm_off` | 0x06eb38 | 0x6eb54 |
| `sde_encoder_init` | 0x08ec30 | 0x8f698 |
| `dsi_display_status_reg_read` | 0x1611a0 | 0x161230 |
| `dsi_display_post_enable` | 0x172bcc | 0x172e20 |
| `dsi_panel_set_backlight` | 0x174124 | 0x1743ac / 0x17441c |
| `dsi_panel_power_on` | 0x17d4ac | 0x17d580 |
| **`dsi_panel_prepare`** | **0x17dd88** | 0x17de00 |
| `dsi_panel_switch` | 0x17e524 | 0x17e604 |
| `dsi_panel_disable` | 0x17e9e4 | 0x17eb28 |
| `dsi_panel_post_unprepare` | 0x17ec7c | 0x17ed28 |

### 1.3 反汇编证明：出厂序列不在 ko 里

`dsi_panel_prepare`（0x17dd88，252 字节）的关键片段：

```asm
17de00: adrp x1, ...                  ; R_AARCH64_ADR_PREL_PG_HI21 .rodata+0x2b11c
17de04: ldr  x0, [x20]                ; x0 = panel->name
17de08: add  x1, x1, #0x0             ; R_AARCH64_ADD_ABS_LO12_NC .rodata+0x2b11c
17de0c: bl   strcmp
17de10: cbnz w0, 17de2c               ; name != "ILI7838E_TIANMA_MEIZU" -> 跳过
17de14: mov  x0, x20
17de18: bl   __cfi_check / .text+0x17d6f4   ; 某个面板专有动作（复位/供电）
17de1c: mov  w0, #0x2710              ; 10000 us
17de20: mov  w1, #0x2774              ; 10100 us
17de24: mov  w2, #0x2
17de28: bl   usleep_range_state        ; usleep_range(10000, 10100)
17de2c: mov  x0, x20
17de30: mov  w1, wzr                  ; cmd set index = 0
17de34: bl   dsi_panel_tx_cmd_set      ; <-- 命令全部从这里发
```

结论：厂商对这块面板在 `prepare` 里**只加了一个 10ms 延时**，真正的初始化命令走
`dsi_panel_tx_cmd_set(panel, DSI_CMD_SET_PRE_ON /* = 0 */)` → 读 `panel->cmd_sets[0]`，
而 `cmd_sets[]` 是 `dsi_panel_parse_cmd_sets()` 从 DT 属性 `qcom,mdss-dsi-pre-on-command / -on-command` 解析出来的。

`.rodata` 里确实存在这批属性名（30+ 个），是同一结论的另一半证据：

```
0x25521 qcom,mdss-dsi-on-command          0x5f25f qcom,mdss-dsi-pre-on-command
0x44c4b qcom,mdss-dsi-post-off-command-…  0x50902 qcom,mdss-dsi-post-mode-switch-on-command
0x623b5 qcom,mdss-dsi-timing-switch-command-state   …
```

### 1.4 结构扫描：负结果（重要，别在这里浪费时间）

按要求在 `.rodata`（0x75830 字节）里搜索 `dsi_cmd_desc` 特征。试了两种头布局，各要求「连续两条命令都合法」（dtype ∈ {05,15,39,29,06,13,03,23,04}、last ∈ {0,1}、vc ≤ 3、ack ≤ 1、wait < 0x2000、0 < dlen ≤ 0x100）：

| 布局假设 | 命中 |
|---|---|
| u32 头 `{dtype,last,vc,ack,wait,dlen}`（24B 头） | **0** |
| 紧凑 6B 头 `{dtype,last,vc,ack,wait,dlen}`（各 1B） | 1（0x5ddc8，人工核对是随机字节误命中，后续命令不构成合法链） |

**结论：`msm_drm.ko` 里没有任何静态初始化序列表。** 与 §1.3 的代码路径一致——这是高通标准设计（DT 驱动），不是魅族删了什么东西。

### 1.5 改道 dtbo：真正的位置

`dtbo.img`（2,097,152 B，magic `0xd7b7ab1e`，5 个 entry，`dt_entry_size=32`）：

| idx | dt_size | dt_offset | board-id | 机型 |
|---|---|---|---|---|
| 0 | 392,430 | 192 | 0x03 0x01 | M2468 B1 |
| 1 | 391,465 | 392,622 | 0x03 0x02 | M2468 B1.1 |
| 2 | 393,653 | 784,087 | 0x03 0x03 | M2468 B2 |
| 3 | 396,016 | 1,177,740 | 0x03 0x04 | M2468 B2.1 |
| 4 | 391,074 | 1,573,756 | 0x03 0x05 | **M2468 MP（本机运行时）** |

`dtc -I dtb -O dts` 反编译 entry4（15,956 行）后，`__symbols__` 直接给出路径：

```
dsi_xjmz_amoled_tianma_cmd = "/fragment@71/__overlay__/qcom,mdss_mdp@ae00000/qcom,mdss_dsi_xjmz_amoled_tianma_cmd";
```

即 **`fragment@71` → `qcom,mdss_mdp@ae00000` → `qcom,mdss_dsi_xjmz_amoled_tianma_cmd`**（dts 行 14383–14816，92,662 字节）。节点内含 5 个 timing 子节点，每个都有自己的 `qcom,mdss-dsi-on-command`。

复现：

```bash
python3 - <<'EOF'
import struct
d=open('dtbo.img','rb').read()
magic,total,hsz,esize,ecount,eoff,psz,ver=struct.unpack_from('>8I',d,0)
for i in range(ecount):
    ds,do,id_,rev=struct.unpack_from('>4I',d,eoff+i*esize)
    open(f'entry{i}.dtb','wb').write(d[do:do+ds])
EOF
for i in 0 1 2 3 4; do dtc -I dtb -O dts -o entry$i.dts entry$i.dtb; done
grep -n 'tianma' entry4.dts
```

> 注意 `dtbo.img` 的 entry 是 **overlay**（`fragment@N` + `__fixups__`），不是完整 DTB。`dtc` 能直接解，节点路径里带 `__overlay__` 是正常的。

### 1.6 命令流格式：实测 7 字节头（和网上文档的 6 字节不一样）

网上（含高通文档、大量论坛帖）流传的格式是「6 字节头：dtype, last, vc, ack, wait, dlen」。**这块面板的实测不是**。

在 5 个 `on-command` blob 上穷举 6 种候选布局，判据是「必须精确消耗到 blob 末尾、所有 dtype 合法、wait 物理合理」：

| 布局 | 精确解析成功 | 5 个 blob 的命令数 | max(wait) |
|---|---|---|---|
| 6B `{dtype,last,vc,ack,wait8,dlen8}` BE/LE | **0 / 5** | — | — |
| **7B `{dtype,last,vc,flags, wait16 LE, dlen8}`** | **5 / 5** | 84 / 84 / 84 / 100 / 98 | **100** |
| 7B `{…, wait16 BE, dlen8}` | 5 / 5 | 同上 | 25600（不可能） |
| 8B `{…, wait16, dlen16}` BE/LE | **0 / 5** | — | — |

物理佐证（7B/LE 解读）：

```
#78  0x15 wait=100ms dlen=2  "11 00"   <- exit-sleep，后等 100ms（ILI 规格值）
#83  0x15 wait= 20ms dlen=1  "29"      <- display-on，后等 20ms（ILI 规格值）
```

**交叉验证**：把同一布局套到面板节点里**全部 78 个** `qcom,mdss-dsi-*-command` 属性上，**77 个精确解析到末尾**（`off-command`、`adfr-on/off`、`nolp`、`hbm`、`aod-*`、`pwm-dc-mode` 等，每个 2–47 条不等）。唯一不匹配的是 `qcom,mdss-dsi-panel-status-command`（`<0x6010001 0x10a …>`，那是 ESD 读寄存器用的另一种结构，本来就不是命令序列）。一个错误的位宽不可能让 77 个独立属性同时整数对齐——这是布局判断最硬的一条旁证。

所以本机的真实排布：

```c
struct dsi_cmd_desc_m2468 {   /* 7 字节头，紧跟 dlen 字节 payload */
    u8  dtype;      /* 0x05/0x15 = DCS short write, 0x39 = DCS long write */
    u8  last;       /* 1 = 该 cmd set 的最后一条 */
    u8  vc;
    u8  flags;      /* 实测 0x00 与 0x40 两种取值，语义未定（见 §2.7-4） */
    u16 wait;       /* 小端，毫秒 */
    u8  dlen;
    u8  payload[];
};
```

> ⚠️ 这个差异值得记住：如果照 6 字节头写解析器，会把 1182 字节切错位（我第一版就是 17 条 vs 真实 84 条），并且静默「成功」——不校验长度根本发现不了。

### 1.7 提取结果

| 刷新率 | 命令数 | 字节数 | 与 120Hz 的差异 |
|---|---|---|---|
| **120 Hz（默认，DT 第一个 timing）** | **84** | 1182 | 基准 |
| 144 Hz | 84 | 1182 | 仅 1 条：`39 00 00 00 00 00 02 81 01`（页 0x2d 寄存器 0x81 = 0x01） |
| 90 Hz | 84 | 1182 | 仅 1 条：`… 81 03` |
| 60 Hz | 100 | 1362 | 多 16 条（内嵌该档 timing 寄存器） |
| 30 Hz | 98 | 1340 | 多 14 条 |

**这是个很干净的结构**：120/144/90 三档初始化完全一样，只靠页 `0x2d` 的寄存器 `0x81` 选刷新率（0x00 / 0x01 / 0x03）；60/30 因为要改更多 timing 才多出命令。

#### 120Hz 完整序列（84 条，dtype + payload）

```
idx  dtype  last vc flg  wait  dlen  payload (hex)
---  -----  ---- -- ---  ----  ----  --------------
  0  0x39     0  0 0x00     0     4  ff 08 38 08
  1  0x39     0  0 0x00     0     2  c8 62
  2  0x39     0  0 0x00     0     4  ff 08 38 21
  3  0x39     0  0 0x00     0     2  93 01
  4  0x39     0  0 0x00     0     2  a4 18
  5  0x39     0  0 0x00     0     4  ff 08 38 19
  6  0x39     0  0 0x00     0     2  c5 02
  7  0x39     0  0 0x00     0     4  ff 08 38 23
  8  0x39     0  0 0x00     0     2  97 0a
  9  0x39     0  0 0x00     0     4  ff 08 38 2d
 10  0x39     0  0 0x00     0     2  ce 52
 11  0x39     0  0 0x00     0     4  ff 08 38 1f
 12  0x39     0  0 0x00     0     2  aa 04
 13  0x39     0  0 0x00     0     4  ff 08 38 07
 14  0x39     0  0 0x00     0     2  8a 01
 15  0x39     0  0 0x00     0     3  8b 11 e0
 16  0x39     0  0 0x00     0   100  81 00 00 00 00 00 12 00 00 ab 10 80 0a dc 04 f0 00 0a 02 78 02 78 02 00 02 3d 00 20 00 e0 00 08 00 0c 0a ab 08 bd 18 00 11 00 07 10 20 00 06 0f 0f 33 0e 1c 2a 38 46 54 62 69 70 77 79 7b 7d 7e 02 02 22 00 2a 40 2a be 3a fc 3a fa 3a f8 3b 38 3b 78 3b b6 4b b6 4b f4 4b f4 6c 34 84 74 74 00 00 00 00 00
 17  0x39     0  0 0x00     0     4  ff 08 38 2d
 18  0x39     0  0 0x00     0     2  80 11
 19  0x39     0  0 0x00     0     2  81 00
 20  0x39     0  0 0x00     0     4  ff 08 38 02
 21  0x39     0  0 0x00     0     2  b6 b0
 22  0x39     0  0 0x00     0     2  f8 01
 23  0x39     0  0 0x00     0     4  ff 08 38 20
 24  0x39     0  0 0x00     0     2  b3 50
 25  0x39     0  0 0x00     0     2  b5 03
 26  0x39     0  0 0x00     0     4  ff 08 38 31
 27  0x39     0  0 0x00     0     2  d0 81
 28  0x39     0  0 0x00     1     2  a0 b3
 29  0x39     0  0 0x00     0    19  80 f0 b0 84 57 2a d6 a9 7c 50 f0 60 50 48 10 f0 d4 c0 a0
 30  0x39     0  0 0x00     0    19  81 f0 9e 76 4f 26 da b1 8a 62 f0 60 50 40 10 f0 d8 d0 a0
 31  0x39     0  0 0x00     0    19  82 f0 77 59 3b 1c e4 c5 a7 89 f0 50 40 3e 10 f0 e8 d0 b0
 32  0x39     0  0 0x00     0    19  83 f0 8e 6a 46 22 de ba 96 72 f0 60 50 40 0e f2 e4 d0 c0
 33  0x39     0  0 0x00     0    19  84 f0 88 65 43 21 df bd 9b 78 f0 40 30 38 0e f6 f0 e8 d8
 34  0x39     0  0 0x00     0    19  85 f0 71 55 38 1b e5 c8 ab 8f f0 40 30 20 0a f6 f0 e8 d8
 35  0x39     0  0 0x00     0    19  86 f0 b0 84 57 2a d6 a9 7c 50 f0 60 50 48 10 f0 d4 c0 a0
 36  0x39     0  0 0x00     0    19  87 f0 9e 76 4f 26 da b1 8a 62 f0 60 50 40 10 f0 d8 d0 a0
 37  0x39     0  0 0x00     0    19  88 f0 77 59 3b 1c e4 c5 a7 89 f0 50 40 3e 10 f0 e8 d0 b0
 38  0x39     0  0 0x00     0    19  89 f0 8e 6a 46 22 de ba 96 72 f0 60 50 40 0e f2 e4 d0 c0
 39  0x39     0  0 0x00     0    19  8a f0 88 65 43 21 df bd 9b 78 f0 40 30 38 0e f6 f0 e8 d8
 40  0x39     0  0 0x00     1    19  8b f0 71 55 38 1b e5 c8 ab 8f f0 40 30 20 0a f6 f0 e8 d8
 41  0x39     0  0 0x00     0     4  ff 08 38 31
 42  0x39     0  0 0x00     0     2  d0 80
 43  0x39     0  0 0x00     0     2  a3 00
 44  0x39     0  0 0x00     0    11  90 02 03 04 05 07 02 03 04 05 07
 45  0x39     0  0 0x00     0     7  91 04 44 55 03 05 08
 46  0x39     0  0 0x00     0     7  92 04 44 55 03 05 08
 47  0x39     0  0 0x00     0     7  93 04 44 55 03 05 08
 48  0x39     0  0 0x00     0     9  8f 40 40 40 40 40 40 40 40
 49  0x39     0  0 0x00     0     9  8c 10 10 0e 08 00 00 00 00
 50  0x39     0  0 0x00     0     9  8d 10 0c 0c 08 08 00 00 00
 51  0x39     0  0 0x00     0     7  8e 02 00 08 00 0f 70
 52  0x39     0  0 0x00     0     4  ff 08 38 63
 53  0x39     0  0 0x00     0     2  80 40
 54  0x39     0  0 0x00     0     7  81 00 00 00 00 ff ff
 55  0x39     0  0 0x00     0     4  ff 08 38 00
 56  0x39     0  0 0x00     0     2  35 00
 57  0x39     0  0 0x00     0     2  53 20
 58  0x39     0  0 0x00     0     2  95 10
 59  0x39     0  0 0x00     0     4  ff 08 38 1f
 60  0x39     0  0 0x00     0     6  89 44 00 00 f0 44
 61  0x39     0  0 0x40     0     4  ff 08 38 20
 62  0x39     0  0 0x40     0     2  bd 45
 63  0x39     0  0 0x40     0     2  be 65
 64  0x39     0  0 0x40     0     4  ff 08 38 17
 65  0x39     0  0 0x00     0     2  a0 40
 66  0x39     0  0 0x00     0     4  ff 08 38 06
 67  0x39     0  0 0x00     0     2  a1 00
 68  0x39     0  0 0x00     0     2  d2 01
 69  0x39     0  0 0x00     0     4  ff 08 38 06
 70  0x39     0  0 0x00     0     2  c6 01
 71  0x39     0  0 0x00     0     4  ff 08 38 08
 72  0x39     0  0 0x00     0     2  d2 05
 73  0x39     0  0 0x00     0     2  d3 01
 74  0x39     0  0 0x00     0     4  ff 08 38 08
 75  0x39     0  0 0x00     0     9  ed ff ff ff f7 ff e7 45 ff
 76  0x39     0  0 0x00     0     9  ee ff ff c1 f8 21 c0 80 10
 77  0x39     0  0 0x00     0     4  ff 08 38 00
 78  0x15     0  0 0x00   100     2  11 00   <- exit-sleep (DCS 0x11), wait 100 ms
 79  0x39     0  0 0x00     0     3  51 00 00
 80  0x39     0  0 0x00     0     4  ff 08 38 53
 81  0x39     0  0 0x00     0     4  88 40 80 f0
 82  0x39     0  0 0x00     0     4  ff 08 38 00
 83  0x15     0  0 0x00    20     1  29    <- display-on (DCS 0x29), wait 20 ms
```

### 1.8 面板参数（原厂 dtbo 实测值）

| 项 | 值 | 备注 |
|---|---|---|
| `qcom,mdss-dsi-panel-name` | `ILI7838E_TIANMA_MEIZU` | 与 ko 里字符串一致 |
| `qcom,mdss-dsi-panel-type` | `dsi_cmd_mode` | **command mode**，不是 video |
| 分辨率 | 1264 × 2780 | `0x4f0 × 0xadc` |
| h: fp/pw/bp | 100 / 16 / 32 | htotal = 1412 |
| v: fp/pw/bp | 100 / 18 / 32 | vtotal = 2930 |
| 120Hz `panel-clockrate` | `0x47868c00` = 1,200,000,000 | DSI bit clock |
| 144Hz `panel-clockrate` | `0x566d3e80` = 1,450,000,000 | |
| 等效 pclk @120Hz | 496,459 kHz | 1412×2930×120/1000 |
| 等效 pclk @60Hz | 248,229 kHz | |
| `qcom,mdss-dsi-reset-sequence` | `<1 10 0 10 1 10>` | 高10ms → 低10ms → 高10ms |
| `compression-mode` | `dsc` | |
| DSC | 8 bpp / 10 bpc / slice 632×10 / 2 slice-per-pkt / version 0x12 / 2 encoders | 632 = 1264/2 → 左右各一个 encoder |
| `qcom,mdss-dsi-bpp` | 8 | |
| `qcom,mdss-dsi-panel-framerate` | 120, 144, 90, 60, 30（DT 顺序） | 顺序即 timing index |
| `qcom,display-topology` | `<2 2 1>` | 2 LM / 2 enc / 1 intf |
| TE | `qcom,mdss-dsi-te-using-te-pin`，TE gpio = TLMM 86，dynamic-TE gpio = 87 | |
| 复位 gpio | TLMM 133 | `qcom,platform-reset-gpio = <0xffffffff 0x85 0>` |
| 背光 | `bl_ctrl_dcs`，bl-min 2 / bl-max 4095 (0xfff) | DCS 0x51 写亮度 |
| ESD | `qcom,esd-check-enabled`，读 0x0a / 0xb0，期望 `9c 00` | |
| 物理尺寸 | 71 × 157 mm | `0x47 × 0x9d` |

### 1.9 产物文件

| 文件 | 内容 |
|---|---|
| `_tmp/m2468_fw/extract/on_120hz.txt` | 120Hz 84 条命令解码表（含 DCS 语义标注） |
| `_tmp/m2468_fw/extract/on_144hz.txt` / `on_90hz.txt` / `on_60hz.txt` / `on_30hz.txt` | 其余 4 档 on-command |
| `_tmp/m2468_fw/extract/<prop>_t0..t4.txt` | 其余属性（off / nolp / hbm / aod / adfr / pwm-dc …），`t0..t4` = DT 内时序槽位 |
| `_tmp/m2468_fw/extract/_unparsed.txt` | 唯一不适配 7 字节头的属性（`panel-status-command`，另一结构） |
| `_tmp/m2468_fw/extract/ili7838e_seq.h` | **可直接 include 的 C 数组**（5 个 `static const u8 ili7838e_on_XXhz[]`，DT 线格式原样） |
| `_tmp/m2468_fw/extract_all.py` | 全量解析器（含 7 字节头实现，可复用） |
| `_tmp/m2468_fw/dtbo/entry{0..4}.dts` | 5 个 dtbo entry 的反编译结果 |
| `_tmp/m2468_fw/dtbo/panel_node.dts` | 面板节点单独摘出（92 KB） |
| `_tmp/m2468_fw/fakepanel/` | 假 panel 驱动 + Makefile（已编译验证） |

---

## 2. 任务 B：假 panel 能不能建出 card0

### 2.1 根因（源码级，不是猜）

`drivers/gpu/drm/msm/dsi/dsi.c`：

```c
static int dsi_bind(struct device *dev, struct device *master, void *data)
{
        ...
        ext_bridge = devm_drm_of_get_bridge(&msm_dsi->pdev->dev,
                                            msm_dsi->pdev->dev.of_node, 1, 0);
        if (IS_ERR(ext_bridge))
                return PTR_ERR(ext_bridge);      /* <-- 整个 component bind 挂掉 */
        msm_dsi->next_bridge = ext_bridge;
        ...
}
```

链路是：`dsi_bind()` 失败 → 组件 `-EPROBE_DEFER`/`-ENODEV` → `component_master_add_with_match()`（`msm_drv.c:1107`）永远等不到全部组件 → **`msm_drm_bind()` 不执行 → `drm_dev_register()`（`msm_drv.c:177`）不执行 → 没有 card0**。

这正好解释现场症状：`msm-mdss / msm_dpu / msm_dsi / msm_dsi_phy` 全都 probe 成功（它们各自 probe），但 `/sys/class/drm` 只有 `version`。

`devm_drm_of_get_bridge()` 的三种返回（`drivers/gpu/drm/drm_of.c` + `bridge/panel.c:505`）：

| DT 状态 | 返回 | 后果 |
|---|---|---|
| 节点没有 `port@1` 图 | `-ENODEV` | 硬失败，永久无 card0 |
| 有 endpoint，但对面节点无驱动 | `-EPROBE_DEFER` | 无限延迟，症状同上 |
| 对面节点是已注册的 `drm_panel` | ✅ 自动 `devm_drm_panel_bridge_add()` 包成 bridge | 成功 |

`CONFIG_DRM_PANEL_BRIDGE=y` 已确认（否则这个函数直接 stub 返回 `-ENODEV`，那是另一种死法）。

### 2.2 现场命中的是哪一条 —— 这是本次最有价值的发现

`arch/arm64/boot/dts/qcom/sm8550-meizu-21note73.dts`（现用板级 DTS）**早就有 panel 节点和 endpoint**：

```dts
&mdss_dsi0 {
        status = "okay";
        display_panel: panel@0 {
                compatible = "boe,meizu20-amoled-fhd";   /* <-- 注意 */
                reg = <0>;
                pinctrl-names = "default", "sleep";
                vddio-supply = <&panel_vddio>;
                vdd-supply   = <&panel_vdd>;
                vci-supply   = <&panel_vci>;
                reset-gpios  = <&tlmm 133 GPIO_ACTIVE_LOW>;
                port {
                        panel0_in: endpoint {
                                remote-endpoint = <&mdss_dsi0_out>;
                        };
                };
        };
};

&mdss_dsi0_out {
        remote-endpoint = <&panel0_in>;
        data-lanes = <0 1 2 3>;
        qcom,te-source = "mdp_vsync_p";
};
```

图是通的、端口号是对的（`port@1/endpoint@0`）、`panel0_in ↔ mdss_dsi0_out` 双向闭合。

而 `drivers/gpu/drm/panel/panel-boe-meizu20.c:1539` 里：

```c
{ .compatible = "boe,meizu20-amoled-fhd" },
```

**compatible 完全匹配**。但 `.config`：

```
# CONFIG_DRM_PANEL_BOE_MEIZU20 is not set
```

→ 驱动没编进内核 → `of_drm_find_panel()` 返回 `-EPROBE_DEFER` → 就是上表第二行。

**硬证据（直接查现用 vmlinux 符号，不是靠推理）**：

```
$ aarch64-linux-gnu-nm /home/shrp/lmp73/vmlinux | grep -ciE 'boe_meizu20|ili7838|ili9882'
0                                        <-- 一个面板驱动都没有
$ aarch64-linux-gnu-nm /home/shrp/lmp73/vmlinux | grep -c ' [TtDd] drm_panel_add$'
1                                        <-- 框架核心是全内建的
$ find /home/shrp/lmp73/drivers/gpu/drm/panel -name '*.ko'
                                         <-- 树里连一个面板 .ko 都没编出来
```

而 DSI 侧组件全在：

```
dsi_bind              1
devm_drm_of_get_bridge 1
drm_panel_bridge_add   1
dsi_mgr_bridge_attach  1
```

即：**框架齐了，一个能挂上去的 panel 都没有**。这就是 `card0` 缺失的完整解释。

> 两个推论：① 必须设成 `=y`，设成 `=m` 还不够——initramfs 里没有这些 .ko，照样 defer；② 若之前刷的 Image 不是用这份 `.config` 编的，结论要按实际 Image 重核（本次核对的 Image 时间戳 2026-10-29 00:57 与本树 `vmlinux` 一致）。

**所以「没有 card0」不是缺驱动代码，是缺一个 `=y`。**（顺带说明：那份驱动是给 meizu20/m2381 的 BOE 1080×2400 写的，模式与本机 1264×2780 不符，但**只要它能 probe，card0 就会出来**——这正是我们这一阶段要的。）

### 2.3 三条路线对比

| 路线 | 动作 | 工作量 | 得到什么 | 风险 |
|---|---|---|---|---|
| **A. 开 Kconfig**（推荐先做） | `CONFIG_DRM_PANEL_BOE_MEIZU20=y`（**必须 `=y`，`=m` 无效**），重建 | 1 行 + 一次编译 | card0 + connector，mode 是 1080×2400（错的） | 最小。mode 不匹配不影响注册；真出图会花屏 |
| **B. 假 panel**（本文代码） | 加一个驱动 + 改 compatible | ~200 行，已有成品 | card0 + **正确的 1264×2780 mode**，可控可调 | 中：mode 可能被 OPP 检查判掉（不影响 card0）；不显示 |
| **C. 真 ili7838e 驱动** | 在 B 的骨架上灌序列表 + DSC | 大（DSC 是硬骨头） | 真正点亮 | 高：msm 的 DSC 路径 + cmd mode + TE 时序 |

建议顺序 **A → B → C**：A 用 10 分钟把「DSI 是不是唯一阻塞点」这件事判掉，别一上来就写驱动。

### 2.4 假 panel 驱动（已编译验证）

设计要点：

1. **必须是 video mode**（`MIPI_DSI_MODE_VIDEO`）。真面板是 cmd mode，但没有初始化序列的 cmd mode 面板会让控制器一直在等 TE/命令完成，video mode 至少能让 DSI 链路自己跑起来。这只是脚手架，不是终态。
2. `get_modes` 给 3 个 mode：1264×2780@60（preferred）、@30、640×480@60（保底，防止大时钟被 OPP 判掉时 connector 空模式）。
3. 不上背光、不发任何 DCS 命令——目标只是 `card0`。
4. 供电用 `devm_regulator_get_optional()`，缺 supply 不会 `-EPROBE_DEFER`（避免又掉进同一个坑）。
5. 用 `devm_drm_panel_alloc()` + `devm_drm_panel_add()`（7.3 的 API，老的 `drm_panel_init()` 已不是首选）。

完整代码（`_tmp/m2468_fw/fakepanel/panel-m2468-fake.c`）：

```c
// SPDX-License-Identifier: GPL-2.0-only
/*
 * panel-m2468-fake.c - minimal "fake" DRM panel for Meizu 21 Note (m2468)
 *
 * Provides the smallest possible drm_panel so that msm dsi_bind()'s
 * devm_drm_of_get_bridge(..., port 1, endpoint 0) resolves and the MSM DRM
 * master registers /dev/dri/card0. Sends NO DSI commands, programs NO DSC:
 * the panel stays dark on purpose.
 */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>

#include <drm/drm_mipi_dsi.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/drm_print.h>

#define M2468_HFP 100
#define M2468_HPW 16
#define M2468_HBP 32
#define M2468_VFP 100
#define M2468_VPW 18
#define M2468_VBP 32
#define M2468_W 1264
#define M2468_H 2780

struct m2468_fake_panel {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct gpio_desc *reset_gpio;
	struct regulator *vddio, *vdd, *vci;
	bool prepared;
};

static inline struct m2468_fake_panel *to_fake(struct drm_panel *p)
{
	return container_of(p, struct m2468_fake_panel, panel);
}

static const struct drm_display_mode m2468_fake_modes[] = {
	{
		.clock = (M2468_W + M2468_HFP + M2468_HPW + M2468_HBP) *
			 (M2468_H + M2468_VFP + M2468_VPW + M2468_VBP) * 60 / 1000,
		.hdisplay = M2468_W,
		.hsync_start = M2468_W + M2468_HFP,
		.hsync_end   = M2468_W + M2468_HFP + M2468_HPW,
		.htotal      = M2468_W + M2468_HFP + M2468_HPW + M2468_HBP,
		.vdisplay = M2468_H,
		.vsync_start = M2468_H + M2468_VFP,
		.vsync_end   = M2468_H + M2468_VFP + M2468_VPW,
		.vtotal      = M2468_H + M2468_VFP + M2468_VPW + M2468_VBP,
		.width_mm = 71, .height_mm = 157,
		.type = DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED,
	},
	{	/* 30 Hz: 1/2 时钟，若 60Hz 被 OPP 判掉先试这个 */
		.clock = (M2468_W + M2468_HFP + M2468_HPW + M2468_HBP) *
			 (M2468_H + M2468_VFP + M2468_VPW + M2468_VBP) * 30 / 1000,
		.hdisplay = M2468_W,
		.hsync_start = M2468_W + M2468_HFP,
		.hsync_end   = M2468_W + M2468_HFP + M2468_HPW,
		.htotal      = M2468_W + M2468_HFP + M2468_HPW + M2468_HBP,
		.vdisplay = M2468_H,
		.vsync_start = M2468_H + M2468_VFP,
		.vsync_end   = M2468_H + M2468_VFP + M2468_VPW,
		.vtotal      = M2468_H + M2468_VFP + M2468_VPW + M2468_VBP,
		.width_mm = 71, .height_mm = 157,
		.type = DRM_MODE_TYPE_DRIVER,
	},
	{	/* 保底模式 */
		.clock = 25175,
		.hdisplay = 640, .hsync_start = 656, .hsync_end = 752, .htotal = 800,
		.vdisplay = 480, .vsync_start = 490, .vsync_end = 492, .vtotal = 525,
		.width_mm = 170, .height_mm = 127,
		.type = DRM_MODE_TYPE_DRIVER,
	},
};

static int m2468_fake_get_modes(struct drm_panel *panel,
				struct drm_connector *connector)
{
	unsigned int i;
	int count = 0;

	for (i = 0; i < ARRAY_SIZE(m2468_fake_modes); i++) {
		struct drm_display_mode *mode;

		mode = drm_mode_duplicate(connector->dev, &m2468_fake_modes[i]);
		if (!mode) {
			DRM_ERROR("failed to add mode %ux%u\n",
				  m2468_fake_modes[i].hdisplay,
				  m2468_fake_modes[i].vdisplay);
			continue;
		}
		drm_mode_set_name(mode);
		mode->type |= DRM_MODE_TYPE_DRIVER;
		drm_mode_probed_add(connector, mode);
		count++;
	}

	connector->display_info.width_mm = 71;
	connector->display_info.height_mm = 157;
	connector->display_info.bpc = 8;

	return count;
}

static int m2468_fake_prepare(struct drm_panel *panel)
{
	struct m2468_fake_panel *ctx = to_fake(panel);
	int ret;

	if (ctx->prepared)
		return 0;

	ret = regulator_enable(ctx->vddio);  if (ret) return ret;
	ret = regulator_enable(ctx->vdd);    if (ret) goto err_vdd;
	ret = regulator_enable(ctx->vci);    if (ret) goto err_vci;

	if (ctx->reset_gpio) {
		/* 原厂 qcom,mdss-dsi-reset-sequence = <1 10 0 10 1 10> */
		gpiod_set_value_cansleep(ctx->reset_gpio, 1);
		usleep_range(10000, 11000);
		gpiod_set_value_cansleep(ctx->reset_gpio, 0);
		usleep_range(10000, 11000);
		gpiod_set_value_cansleep(ctx->reset_gpio, 1);
		usleep_range(10000, 11000);
	}

	/*
	 * 这里故意不发任何 DSI 命令。
	 * 要做真驱动：用 mipi_dsi_dcs_write_buffer() 回放 ili7838e_seq.h，
	 * 并按 §1.8 配 dsi->dsc（8bpp / 10bpc / 632x10 / 2 encoders）。
	 */
	ctx->prepared = true;
	return 0;

err_vci:
	regulator_disable(ctx->vdd);
err_vdd:
	regulator_disable(ctx->vddio);
	return ret;
}

static int m2468_fake_enable(struct drm_panel *panel)   { return 0; }
static int m2468_fake_disable(struct drm_panel *panel)  { return 0; }

static int m2468_fake_unprepare(struct drm_panel *panel)
{
	struct m2468_fake_panel *ctx = to_fake(panel);

	if (!ctx->prepared)
		return 0;

	if (ctx->reset_gpio)
		gpiod_set_value_cansleep(ctx->reset_gpio, 0);

	regulator_disable(ctx->vci);
	regulator_disable(ctx->vdd);
	regulator_disable(ctx->vddio);

	ctx->prepared = false;
	return 0;
}

static const struct drm_panel_funcs m2468_fake_panel_funcs = {
	.prepare   = m2468_fake_prepare,
	.enable    = m2468_fake_enable,
	.disable   = m2468_fake_disable,
	.unprepare = m2468_fake_unprepare,
	.get_modes = m2468_fake_get_modes,
};

static int m2468_fake_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct m2468_fake_panel *ctx;
	int ret;

	ctx = devm_drm_panel_alloc(dev, struct m2468_fake_panel, panel,
				   &m2468_fake_panel_funcs,
				   DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(ctx))
		return PTR_ERR(ctx);

	ctx->dsi = dsi;

	/* optional：缺 supply 不 defer */
	ctx->vddio = devm_regulator_get_optional(dev, "vddio");
	if (IS_ERR(ctx->vddio)) ctx->vddio = NULL;
	ctx->vdd = devm_regulator_get_optional(dev, "vdd");
	if (IS_ERR(ctx->vdd))   ctx->vdd = NULL;
	ctx->vci = devm_regulator_get_optional(dev, "vci");
	if (IS_ERR(ctx->vci))   ctx->vci = NULL;

	ctx->reset_gpio = devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(ctx->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(ctx->reset_gpio),
				     "cannot get reset gpio\n");

	dsi->lanes = 4;                      /* dsi_host_attach 要求 <= num_data_lanes */
	dsi->format = MIPI_DSI_FMT_RGB888;
	dsi->mode_flags = MIPI_DSI_MODE_VIDEO |
			  MIPI_DSI_MODE_VIDEO_SYNC_PULSE |
			  MIPI_DSI_MODE_LPM |
			  MIPI_DSI_MODE_NO_EOT_PACKET;

	mipi_dsi_set_drvdata(dsi, ctx);

	ret = devm_drm_panel_add(dev, &ctx->panel);
	if (ret)
		return dev_err_probe(dev, ret, "failed to add panel\n");

	dev_info(dev, "fake panel registered: 1264x2780, 4 lanes, video mode "
		      "(no init sequence - displays nothing, registers card0)\n");
	return 0;
}

static void m2468_fake_remove(struct mipi_dsi_device *dsi)
{
	struct m2468_fake_panel *ctx = mipi_dsi_get_drvdata(dsi);
	m2468_fake_unprepare(&ctx->panel);
}

static const struct of_device_id m2468_fake_of_match[] = {
	{ .compatible = "meizu,m2468-fakepanel" },
	{ }
};
MODULE_DEVICE_TABLE(of, m2468_fake_of_match);

static struct mipi_dsi_driver m2468_fake_driver = {
	.probe  = m2468_fake_probe,
	.remove = m2468_fake_remove,
	.driver = {
		.name = "panel-m2468-fake",
		.of_match_table = m2468_fake_of_match,
	},
};
module_mipi_dsi_driver(m2468_fake_driver);

MODULE_AUTHOR("m2468 bring-up");
MODULE_DESCRIPTION("Minimal fake DSI panel for Meizu 21 Note (card0 bring-up)");
MODULE_LICENSE("GPL");
```

**编译验证（真跑了，不是「应该能编」）**：

```
$ make -C /home/shrp/lmp73 M=$PWD ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- W=1 panel-m2468-fake.o
  CC [M]  panel-m2468-fake.o
# 零 error 零 warning

$ for s in __devm_drm_panel_alloc mipi_dsi_driver_register_full drm_mode_duplicate \
           drm_mode_probed_add regulator_enable gpiod_set_value_cansleep usleep_range_state __drm_err; do
      aarch64-linux-gnu-nm /home/shrp/lmp73/vmlinux | grep -c " [TtDdRr] $s$"; done
1 1 1 1 1 1 1 1        # 全部符号在 vmlinux 里，in-tree 内建必然链接成功
```

> `make ... modules` 的 modpost 阶段会报 `symbol ... undefined`，唯一原因是 `/home/shrp/lmp73/Module.symvers` 缺失（内核几乎全 `=y`，没生成过模块符号表），**不是代码问题**。要做成 .ko 需要先补 `Module.symvers`；直接内建（`obj-y`）则无此问题。

### 2.5 DTS 写法

**最小改动**（复用现有节点，只换 compatible —— 推荐先用这个验证）：

```dts
/* sm8550-meizu-21note73.dts:1059 附近，其余属性全部保留 */
display_panel: panel@0 {
-       compatible = "boe,meizu20-amoled-fhd";
+       compatible = "meizu,m2468-fakepanel";
        reg = <0>;
        /* pinctrl / supplies / reset-gpios / port 一律不动 */
};
```

**或者**新增一个独立节点（想同时保留 boe 驱动做对比时）：

```dts
&mdss_dsi0 {
	status = "okay";

	panel@0 {
		compatible = "meizu,m2468-fakepanel";
		reg = <0>;

		vddio-supply = <&panel_vddio>;
		vdd-supply   = <&panel_vdd>;
		vci-supply   = <&panel_vci>;
		reset-gpios  = <&tlmm 133 GPIO_ACTIVE_LOW>;

		port {
			fake_panel_in: endpoint {
				remote-endpoint = <&mdss_dsi0_out>;
			};
		};
	};
};

&mdss_dsi0_out {
	remote-endpoint = <&fake_panel_in>;
	data-lanes = <0 1 2 3>;
};
```

Kconfig 侧（若做成内建，最小侵入）：

```
# drivers/gpu/drm/panel/Kconfig 里给 CONFIG_DRM_PANEL_M2468_FAKE 加一条，
# 或在 .config 直接 CONFIG_DRM_PANEL_M2468_FAKE=y 后 make olddefconfig
```

> 三个硬约束：① 端点必须在 **`port@1` / `endpoint@0`**（`dsi_bind` 写死的），别改成 `port@0`；② 面板节点必须是 DSI 控制器的**子节点且带 `reg = <0>`**，才会被 `of_mipi_dsi_device_add()` 枚举成 `mipi_dsi_device`；③ `remote-endpoint` 必须双向闭合。

### 2.6 上机验证步骤

```bash
# 1) 面板驱动是否绑上（这一步失败，后面全白搭）
dmesg | grep -iE 'panel-m2468-fake|fake panel registered'
ls -l /sys/bus/mipi-dsi/devices/

# 2) DSI 组件是否 bind 成功
dmesg | grep -iE 'msm_dsi|dsi_bind|component.*bind|deferred probe'

# 3) 关键判据
ls -l /dev/dri/                 # 期望出现 card0
cat /sys/class/drm/version
ls /sys/class/drm/              # 期望 card0-DSI-1

# 4) 看 connector 和 mode
modetest -M msm -c
modetest -M msm -p             # 看 1264x2780@60 是否在列
```

判读：

| 现象 | 含义 |
|---|---|
| card0 出现 + `card0-DSI-1` connector 有 mode | ✅ 假 panel 路线成立，可以进下一步 |
| card0 出现但 connector 无 mode | mode 被 `mode_valid` 判掉了（OPP/时钟），换 640×480 或删 `operating-points-v2` |
| 仍然没有 card0 | 还有**别的**组件在 defer（DP/GPU），看 `/sys/kernel/debug/devices_deferred`（`CONFIG_DEBUG_DRIVER`）或 dmesg 里的 deferred probe 列表 |

### 2.7 风险与不确定性（按严重度）

1. **`dsi_mgr_bridge_mode_valid` 的 OPP 检查**（最大的单点）：它会用 mode 反算 byte clock，再 `dev_pm_opp_find_freq_ceil()`。若 DSI 节点挂了非空的 OPP 表而没有这个频点 → 返回 `MODE_CLOCK_RANGE`，mode 被判掉。**但这只影响 mode 列表，不影响 card0 注册**，所以对「先要 card0」这个目标不致命。真遇到就退到 640×480 或用 30Hz。
2. **PHY timings 与 mode 不匹配**：现 DTS 的 `qcom,panel-phy-timings`（`<0x03 0x26 0x08 …>`）是 meizu20 BOE 的值（约 1094 Mbps），与我们 1264×2780 的 1.2 Gbps 不是一套。这只在**真正 commit 出图**时炸，卡在 init 阶段不影响 card0。
3. **真面板是 cmd mode + DSC，video mode 只是脚手架**。用假 panel 点亮屏幕是不可能的——它连 0x11/0x29 都不发。这一点不要自欺。
4. **`flags` 字节语义未确定**：7 字节头第 4 字节在 `on-command` 里全是 `0x00`，但在 `timing-switch-command` 里是 `0x40`。我按「不透明标志位」处理，**回放时原样带过去**即可，不影响字节级还原。这条我没有证据下结论，明确标为未解。
5. **序列与 DSC 强耦合**：这些命令里包含大量 DSC PPS/补偿相关寄存器（0x81 的 100 字节表、0x80–0x8b、0x90–0x93 gamma 等）。如果 mainline 侧不按 632×10/8bpp/10bpc 配 DSC，只灌序列大概率黑屏或花屏——**不是序列错，是配套参数错**。
6. **60/30Hz 的 on-command 比 120Hz 多 14–16 条**，说明这两档不是「同序列改一个寄存器」，而是有独立 timing 配置。若先跑 30Hz，用 `on_30hz` 那份，别用 120Hz 那份改。
7. 本次**没有**验证项：真机是否还有第二个 component 在 defer（DP 已 `disabled`，GPU 侧未知）。这个只能上机看 dmesg。

---

## 3. 下一步建议（按投入产出排序）

1. **（10 min，最高优先）路线 A**：`CONFIG_DRM_PANEL_BOE_MEIZU20=y` + `make olddefconfig` + 重建，刷 boot，看 `/dev/dri/card0`。
   - 出来 → 说明「缺 panel 是唯一阻塞点」，任务 B 判定完成，进入出图阶段
   - 不出来 → 用 `/sys/kernel/debug/devices_deferred` 看还有谁在 defer，别再猜
2. **（30 min）路线 B**：把 §2.4 的驱动内建进去（`obj-y`），compatible 换成 `meizu,m2468-fakepanel`，拿到**正确的 1264×2780 mode**。这样 `modetest` 能直接试 modeset，为后面出图铺路。
3. **（半天+）路线 C 第一步：video mode 出图**。先不管 DSC，用 1264×2780@30（pclk 124 MHz，4 lane 约 745 Mbps/lane，非常安全），只发 `0x11` + 100ms + `0x29` + 20ms 三条命令，看能否出稳定灰屏/彩条。这一步能验证 DSI 链路 + PHY + DPU 全通。
4. **（1–2 天）路线 C 第二步：DSC**。按 §1.8 配 `dsi->dsc`（8bpp/10bpc/632×10/2 slices/version 1.2），回放完整 84 条序列，再开 120Hz。
5. **顺手做**：把 `qcom,panel-phy-timings` 换成 1.2 Gbps 对应的一组（原厂 `phy-timings` 属性在 dtbo 里有 4 档：`[03 28 09 0a 1b 27 0a 0b 09 02 04 00 20 10]` 等），别沿用手上这份 meizu20 的。
6. **背光**：`bl_ctrl_dcs`，DCS 0x51 写 0..4095；最小可用值 2，正常最大 4095（`qcom,mdss-brightness-normal-max-level = 0xc51`）。

---

## 4. 附录

### 4.1 复现命令

```bash
# ELF 结构
wsl -e bash -c "readelf -S -W msm_drm.ko | head -50"

# 找字符串
grep -aob 'ILI7838E_TIANMA_MEIZU' msm_drm.ko

# 重定位 xref（关键一步）
python3 xref2.py        # 扫 .rela.text 里 addend == 0x2b11c 的条目

# 反汇编
aarch64-linux-gnu-objdump -d --no-show-raw-insn -r \
    --start-address=0x17dd88 --stop-address=0x17e524 msm_drm.ko

# dtbo → dts（内联段见 §1.5，或存成 split_dtbo.py 后执行）
python3 split_dtbo.py && dtc -I dtb -O dts -o entry4.dts entry4.dtb

# 解序列
python3 extract_seq.py  # -> extract/on_*.txt + ili7838e_seq.h

# 编译假 panel
cd fakepanel && make -C /home/shrp/lmp73 M=$PWD ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- W=1 panel-m2468-fake.o
```

### 4.2 文件清单

| 路径 | 说明 |
|---|---|
| `Desktop/meizu21note_Mu/panel逆向_子代理.md` | 本报告 |
| `_tmp/m2468_fw/extract/on_120hz.txt` … `on_30hz.txt` | 5 档 on-command 解码表 |
| `_tmp/m2468_fw/extract_*.py` | `extract_all.py`（全量解析）/ `extract_seq.py`（首版） |
| `_tmp/m2468_fw/extract/ili7838e_seq.h` | C 数组（可直接 include） |
| `_tmp/m2468_fw/xref.py` / `xref2.py` / `mapfunc.py` / `elf_scan.py` | ELF 分析脚本 |
| `_tmp/m2468_fw/dtbo/entry{0..4}.dts` | 5 个 overlay 反编译 |
| `_tmp/m2468_fw/dtbo/panel_node.dts` | 面板节点摘录（92 KB） |
| `_tmp/m2468_fw/fakepanel/panel-m2468-fake.c` + `Makefile` | 假 panel 驱动（已编译验证） |

### 4.3 一句话留给下一个接手的人

> 序列不在 ko 里，在 `dtbo.img` entry4 的 `fragment@71` 里；格式是 **7 字节头**（不是 6）；
> card0 出不来不是缺代码，是 `CONFIG_DRM_PANEL_BOE_MEIZU20` 没开。
