// SPDX-License-Identifier: GPL-2.0-only
/*
 * panel-meizu-m2468.c - Tianma ILI7838E AMOLED panel for Meizu 21 Note (m2468)
 *
 * Panel: ILI7838E_TIANMA_MEIZU, 1264x2780, 4-lane DSI, cmd mode, DSC.
 *
 * Init sequences were extracted from the stock Android dtbo
 * (fragment@71, qcom,mdss_dsi_xjmz_amoled_tianma_cmd) into
 * ili7838e_seq.h using the 7-byte wire format:
 *
 *   u8  dtype      DCS type (0x05 short write, 0x15 short write+1param,
 *                  0x39 long write)
 *   u8  last       last command in the set
 *   u8  vc         virtual channel
 *   u8  flags      ack / wait flags
 *   u16 wait_ms    delay after this command (little endian)
 *   u8  dlen       payload length
 *   u8  payload[]  parameters
 *
 * Two stages:
 *   PANEL_MODE_FAKE  - register a panel, send nothing (card0 bring-up)
 *   PANEL_MODE_REAL  - send the extracted init sequence
 *
 * Selected at runtime via the "meizu,panel-mode" DT property, so the same
 * kernel image can be switched by editing the DTB only.
 */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/fb.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/regulator/consumer.h>

#include <drm/drm_mipi_dsi.h>
#include <drm/display/drm_dsc_helper.h>
#include <video/mipi_display.h>
#include <drm/drm_modes.h>
#include <drm/drm_panel.h>
#include <drm/drm_print.h>

#include "ili7838e_seq.h"

/* 1264 x 2780, porches from stock dtbo */
#define M2468_W    1264
#define M2468_H    2780
#define M2468_HFP  100
#define M2468_HPW  16
#define M2468_HBP  32
#define M2468_VFP  100
#define M2468_VPW  18
#define M2468_VBP  32

#define M2468_HTOTAL (M2468_W + M2468_HFP + M2468_HPW + M2468_HBP)
#define M2468_VTOTAL (M2468_H + M2468_VFP + M2468_VPW + M2468_VBP)

enum m2468_mode {
	M2468_MODE_FAKE = 0,	/* register card0, send nothing */
	M2468_MODE_REAL,	/* send extracted init sequence */
};

struct m2468_panel {
	struct drm_panel panel;
	struct mipi_dsi_device *dsi;
	struct gpio_desc *reset_gpio;
	struct regulator *vddio;
	struct regulator *vdd;
	struct regulator *vci;
	struct backlight_device *backlight;
	enum m2468_mode mode;
	bool prepared;
	struct drm_dsc_config dsc;
};

static inline struct m2468_panel *to_m2468(struct drm_panel *panel)
{
	return container_of(panel, struct m2468_panel, panel);
}

/*
 * Resolved panel clock for 60 Hz:
 *   (1412 * 2930 * 60) / 1000 = 248,229 kHz
 * That is the DSI byte clock domain value used by msm dsi for the mode.
 */
#define M2468_CLK_120HZ ((M2468_HTOTAL * M2468_VTOTAL * 120) / 1000)
#define M2468_CLK_90HZ  ((M2468_HTOTAL * M2468_VTOTAL * 90) / 1000)
#define M2468_CLK_60HZ  ((M2468_HTOTAL * M2468_VTOTAL * 60) / 1000)
#define M2468_CLK_30HZ  ((M2468_HTOTAL * M2468_VTOTAL * 30) / 1000)

static const struct drm_display_mode m2468_modes[] = {
	{
		/*
		 * Stock dtbo marks the 120 Hz timing as qcom,mdss-dsi-timing-default
		 * and uses the same 1.2 GHz clockrate / porches as 60 Hz and 90 Hz
		 * (LTPO panel - the frame rate is changed inside the panel, not on
		 * the DSI link).  The 0x81 PPS payload is byte-identical between the
		 * 60 Hz and 120 Hz init sequences, so DSC needs no change.
		 */
		.clock		= M2468_CLK_120HZ,
		.hdisplay	= M2468_W,
		.hsync_start	= M2468_W + M2468_HFP,
		.hsync_end	= M2468_W + M2468_HFP + M2468_HPW,
		.htotal		= M2468_HTOTAL,
		.vdisplay	= M2468_H,
		.vsync_start	= M2468_H + M2468_VFP,
		.vsync_end	= M2468_H + M2468_VFP + M2468_VPW,
		.vtotal		= M2468_VTOTAL,
		.width_mm	= 71,
		.height_mm	= 157,
		.type		= DRM_MODE_TYPE_DRIVER | DRM_MODE_TYPE_PREFERRED,
	},
	{
		/* 90 Hz - stock dtbo timing@fhd_90 uses the same 1.2 GHz link clock
		 * and the same porches as 120/60 Hz; frame rate lives inside the
		 * panel, so only the DPU pixel clock differs.
		 */
		.clock		= M2468_CLK_90HZ,
		.hdisplay	= M2468_W,
		.hsync_start	= M2468_W + M2468_HFP,
		.hsync_end	= M2468_W + M2468_HFP + M2468_HPW,
		.htotal		= M2468_HTOTAL,
		.vdisplay	= M2468_H,
		.vsync_start	= M2468_H + M2468_VFP,
		.vsync_end	= M2468_H + M2468_VFP + M2468_VPW,
		.vtotal		= M2468_VTOTAL,
		.width_mm	= 71,
		.height_mm	= 157,
		.type		= DRM_MODE_TYPE_DRIVER,
	},
	{
		.clock		= M2468_CLK_60HZ,
		.hdisplay	= M2468_W,
		.hsync_start	= M2468_W + M2468_HFP,
		.hsync_end	= M2468_W + M2468_HFP + M2468_HPW,
		.htotal		= M2468_HTOTAL,
		.vdisplay	= M2468_H,
		.vsync_start	= M2468_H + M2468_VFP,
		.vsync_end	= M2468_H + M2468_VFP + M2468_VPW,
		.vtotal		= M2468_VTOTAL,
		.width_mm	= 71,
		.height_mm	= 157,
		.type		= DRM_MODE_TYPE_DRIVER,
	},
	{
		.clock		= M2468_CLK_30HZ,
		.hdisplay	= M2468_W,
		.hsync_start	= M2468_W + M2468_HFP,
		.hsync_end	= M2468_W + M2468_HFP + M2468_HPW,
		.htotal		= M2468_HTOTAL,
		.vdisplay	= M2468_H,
		.vsync_start	= M2468_H + M2468_VFP,
		.vsync_end	= M2468_H + M2468_VFP + M2468_VPW,
		.vtotal		= M2468_VTOTAL,
		.width_mm	= 71,
		.height_mm	= 157,
		.type		= DRM_MODE_TYPE_DRIVER,
	},
};

/*
 * Walk the wire-format command blob and replay it over DSI.
 *
 * We deliberately ignore 'last'/'vc'/'flags' - the mainline msm dsi driver
 * already handles commit grouping, and vc is always 0 on this panel.
 */
/* m2468_send_adfr_on() 在下面会调用它，而它定义在本块之后，先声明 */
static int m2468_send_seq(struct m2468_panel *ctx, const u8 *blob, size_t len,
			  const char *what);

/* ===================== E71: LTPO / ADFR =====================
 *
 * 面板默认在 init 序列末尾写入 2D:80 = 0x11（ADFR 引擎关闭，固定帧率）
 * 与 81 = 0x00（120Hz），所以开机即锁 120Hz、静止也满速刷新。
 *
 * 要让 LTPO 真正省电，必须发原厂 dtbo 的完整 18 条 adfr-on 命令集：
 * 它会把 2D:80 置 0x00（ADFR 使能）、配好 BD/BE/A0/B0/B6，
 * 最后用 5 字节 B1 的 payload[4] 指定 min fps（公式 120/fps-1）。
 *
 * 面板随后自行判断：DPU 停推帧时降到 minfps 自刷新，一有新帧立刻回 120Hz。
 * 也就是说降频/升频是面板硬件自动完成的，DPU 侧不需要改造。
 *
 * 注意：早期版本发过一份来自 timing@fhd_30 节点的残版命令集
 * （BD=0x45、无 BE/A0/B0/B6），每次内容变化面板都会重新锁定帧率，
 * 产生整行彩色撕裂线。那是命令集残缺导致，不是 ADFR 机制本身的问题。
 */
static uint m2468_adfr_minfps = 0xFF;
module_param(m2468_adfr_minfps, uint, 0644);
MODULE_PARM_DESC(m2468_adfr_minfps,
	"ADFR min refresh byte: 0xFF=off (default), 0x00=120Hz, 0x01=60Hz, 0x03=30Hz, 0x05=20Hz, 0x0b=10Hz, 0x77=1Hz");

/* 合法 minfps 档位：120/fps-1。0x00=120Hz 0x01=60Hz 0x03=30Hz
 * 0x05=20Hz 0x0b=10Hz 0x77=1Hz。
 * 注意 DPU 侧 KICKOFF_TIMEOUT_MS=84，10Hz(100ms) 和 1Hz(1000ms) 会超时
 * 触发 PANEL_DEAD，所以实际只开放到 20Hz 一档。
 */
static bool m2468_adfr_minfps_valid(u8 m)
{
	return m == 0x00 || m == 0x01 || m == 0x03 || m == 0x05;
}

static int m2468_send_adfr_on(struct m2468_panel *ctx, u8 minfps)
{
	u8 seq[sizeof(ili7838e_adfr_on)];
	size_t off = 0;
	bool found = false;

	if (!m2468_adfr_minfps_valid(minfps)) {
		DRM_ERROR("adfr-on: minfps 0x%02x invalid (only 0x00/0x01/0x03/0x05)\n",
			  minfps);
		return -EINVAL;
	}

	memcpy(seq, ili7838e_adfr_on, sizeof(seq));

	while (off + 7 <= sizeof(seq)) {
		u8 dlen = seq[off + 6];
		u8 *payload;

		if (off + 7 + dlen > sizeof(seq))
			break;
		payload = &seq[off + 7];
		if (dlen == 5 && payload[0] == 0xb1) {
			payload[4] = minfps;
			found = true;
			break;
		}
		off += 7 + dlen;
	}

	if (!found) {
		DRM_ERROR("adfr-on: minfps packet not found in sequence\n");
		return -EINVAL;
	}

	return m2468_send_seq(ctx, seq, sizeof(seq), "adfr-on");
}

static int m2468_send_seq(struct m2468_panel *ctx, const u8 *blob, size_t len,
			  const char *what)
{
	struct mipi_dsi_device *dsi = ctx->dsi;
	size_t off = 0;
	int n = 0, ret;

	while (off + 7 <= len) {
		u8 dtype = blob[off];
		u16 wait_ms = blob[off + 4] | (blob[off + 5] << 8);
		u8 dlen = blob[off + 6];
		const u8 *payload = &blob[off + 7];

		if (off + 7 + dlen > len) {
			DRM_ERROR("%s: truncated command at offset %zu\n",
				  what, off);
			return -EINVAL;
		}

		switch (dtype) {
		case 0x05:	/* DCS short write, no param */
			ret = mipi_dsi_dcs_write_buffer(dsi, payload, 0);
			break;
		case 0x15:	/* DCS short write, 1 param */
			ret = mipi_dsi_dcs_write_buffer(dsi, payload, dlen);
			break;
		case 0x39:	/* DCS long write */
			ret = mipi_dsi_dcs_write_buffer(dsi, payload, dlen);
			break;
		default:
			DRM_DEBUG("%s: skip dtype 0x%02x (dlen %u)\n",
				  what, dtype, dlen);
			ret = 0;
			break;
		}

		if (ret < 0 && ret != -EOPNOTSUPP) {
			DRM_ERROR("%s: cmd %d (dtype 0x%02x) failed: %d\n",
				  what, n, dtype, ret);
			return ret;
		}

		if (wait_ms)
			msleep(wait_ms);

		off += 7 + dlen;
		n++;
	}

	DRM_INFO("%s: sent %d commands (%zu bytes)\n", what, n, len);
	return 0;
}

static int m2468_get_modes(struct drm_panel *panel,
			   struct drm_connector *connector)
{
	unsigned int i;
	int count = 0;

	for (i = 0; i < ARRAY_SIZE(m2468_modes); i++) {
		struct drm_display_mode *mode;

		mode = drm_mode_duplicate(connector->dev, &m2468_modes[i]);
		if (!mode) {
			DRM_ERROR("failed to add mode %ux%u\n",
				  m2468_modes[i].hdisplay,
				  m2468_modes[i].vdisplay);
			continue;
		}
		drm_mode_set_name(mode);
		mode->type |= DRM_MODE_TYPE_DRIVER;
		drm_mode_probed_add(connector, mode);
		count++;
	}

	connector->display_info.width_mm = 71;
	connector->display_info.height_mm = 157;

	return count;
}

static int m2468_prepare(struct drm_panel *panel)
{
	struct m2468_panel *ctx = to_m2468(panel);
	int ret;

	if (ctx->prepared)
		return 0;

	DRM_INFO("prepare: mode=%s\n",
		 ctx->mode == M2468_MODE_REAL ? "REAL" : "FAKE");

	if (ctx->vddio) {
		ret = regulator_enable(ctx->vddio);
		if (ret) {
			DRM_ERROR("vddio enable failed: %d\n", ret);
			return ret;
		}
	}
	if (ctx->vdd) {
		ret = regulator_enable(ctx->vdd);
		if (ret) {
			DRM_ERROR("vdd enable failed: %d\n", ret);
			goto err_vddio;
		}
	}
	if (ctx->vci) {
		ret = regulator_enable(ctx->vci);
		if (ret) {
			DRM_ERROR("vci enable failed: %d\n", ret);
			goto err_vdd;
		}
	}

	msleep(10);

	if (ctx->reset_gpio) {
		/* DT: reset-gpios = <&tlmm 133 GPIO_ACTIVE_LOW>
		 * → logic 1 = assert reset (physical low), logic 0 = release.
		 * 原实现先 0 后 1，等于把面板永久按在复位态，任何初始化命令
		 * 都不会被接受（DCS 读回 0 字节）。正确顺序：assert → release。 */
		gpiod_set_value_cansleep(ctx->reset_gpio, 1);	/* ACTIVE_LOW: logic 1 = assert reset */
		usleep_range(10000, 11000);
		gpiod_set_value_cansleep(ctx->reset_gpio, 0);	/* release */
		usleep_range(120000, 121000);			/* sleep-out 后需 >=120ms */
	}

	if (ctx->mode == M2468_MODE_REAL) {
		/* 原厂 on-command 会把 0x51 亮度写成 0x0000（防开机闪屏），
		 * 真实亮度由 Android 的亮度 HAL 随后设置；本系统没有那个 HAL，
		 * 也没有 backlight 设备，所以必须自己打开，否则 AMOLED 不发光。 */
		static const u8 brightness_on[] = { 0x51, 0x0f, 0xff };

		/*
		 * m2468: use the stock 120 Hz init sequence (84 cmds, 1182 B).
		 * The 60 Hz blob (100 cmds) additionally programs vendor gamma
		 * (DCS 0xB0/0xB1) that the panel's stock 120 Hz path never sends;
		 * running it while the panel is tuned for 120 Hz is the current
		 * suspected source of the content-dependent banding.
		 */
		ret = m2468_send_seq(ctx, ili7838e_on_120hz,
				     sizeof(ili7838e_on_120hz), "init-120hz");

		/*
		 * m2468: the panel boots with LTPO ADFR (adaptive dynamic frame
		 * rate) active.  Nothing in mainline ever turns it off, so the
		 * panel keeps re-locking its own refresh rate every time the
		 * content changes - that re-lock is the full-width coloured
		 * banding ("花屏") seen on rich content, while the framebuffer
		 * stays perfect (grim captures are always clean).
		 *
		 * NOTE: no ADFR sequence is sent on purpose.
		 *
		 * The panel's own on-command already ends with
		 *   2D:80 = 0x11   (ADFR engine OFF, fixed frame rate)
		 *   81    = 0x00   (frame-rate code 0 = 120 Hz)
		 * so the panel powers up already locked at 120 Hz.
		 *
		 * The blob that used to be sent here came from the
		 * timing@fhd_30 node: it sets 2D:80=0x00 (ADFR ON) and
		 * b1 = ff ff ff 03 (min fps = 30 Hz).  That made the panel
		 * re-lock from 30 Hz back to 120 Hz on every content change,
		 * producing full-width 1-3 px tearing lines.
		 */
		if (m2468_adfr_minfps != 0xFF) {
			int adfr_ret = m2468_send_adfr_on(ctx, (u8)m2468_adfr_minfps);

			if (adfr_ret)
				DRM_ERROR("adfr-on failed: %d\n", adfr_ret);
			else
				DRM_INFO("ADFR enabled, minfps=0x%02x\n",
					 (u8)m2468_adfr_minfps);
		}
		if (ret) {
			DRM_ERROR("init sequence failed: %d\n", ret);
			/* 不退出：继续让 DRM 走完，至少能拿到 card0 */
		}

		ret = mipi_dsi_dcs_write_buffer(ctx->dsi, brightness_on,
						sizeof(brightness_on));
		if (ret < 0)
			DRM_ERROR("brightness set failed: %d\n", ret);
		else
			DRM_INFO("brightness set 0x0fff (12-bit max)\n");
	}

	ctx->prepared = true;
	return 0;

err_vdd:
	if (ctx->vdd)
		regulator_disable(ctx->vdd);
err_vddio:
	if (ctx->vddio)
		regulator_disable(ctx->vddio);
	return ret;
}

static int m2468_enable(struct drm_panel *panel)
{
	struct m2468_panel *ctx = to_m2468(panel);

	DRM_INFO("enable\n");

	if (ctx->mode == M2468_MODE_REAL) {
		u8 display_on[] = { 0x29 };
		static const u8 brightness_on[] = { 0x51, 0x0f, 0xff };
		int ret = mipi_dsi_dcs_write_buffer(ctx->dsi, display_on, 1);
		if (ret < 0)
			DRM_ERROR("display on failed: %d\n", ret);
		ret = mipi_dsi_dcs_write_buffer(ctx->dsi, brightness_on,
						sizeof(brightness_on));
		if (ret < 0)
			DRM_ERROR("brightness set failed: %d\n", ret);
	}

	if (ctx->backlight) {
		ctx->backlight->props.power = FB_BLANK_UNBLANK;
		backlight_update_status(ctx->backlight);
	}

	return 0;
}

static int m2468_disable(struct drm_panel *panel)
{
	struct m2468_panel *ctx = to_m2468(panel);

	DRM_INFO("disable\n");

	if (ctx->backlight) {
		ctx->backlight->props.power = FB_BLANK_POWERDOWN;
		backlight_update_status(ctx->backlight);
	}

	if (ctx->mode == M2468_MODE_REAL) {
		u8 display_off[] = { 0x28 };
		mipi_dsi_dcs_write_buffer(ctx->dsi, display_off, 1);
	}

	return 0;
}

static int m2468_unprepare(struct drm_panel *panel)
{
	struct m2468_panel *ctx = to_m2468(panel);

	if (!ctx->prepared)
		return 0;

	DRM_INFO("unprepare\n");

	if (ctx->reset_gpio)
		gpiod_set_value_cansleep(ctx->reset_gpio, 0);

	if (ctx->vci)
		regulator_disable(ctx->vci);
	if (ctx->vdd)
		regulator_disable(ctx->vdd);
	if (ctx->vddio)
		regulator_disable(ctx->vddio);

	ctx->prepared = false;
	return 0;
}

static const struct drm_panel_funcs m2468_panel_funcs = {
	.prepare	= m2468_prepare,
	.enable		= m2468_enable,
	.disable	= m2468_disable,
	.unprepare	= m2468_unprepare,
	.get_modes	= m2468_get_modes,
};

static int m2468_probe(struct mipi_dsi_device *dsi)
{
	struct device *dev = &dsi->dev;
	struct m2468_panel *ctx;
	const char *mode_str;
	u32 vrefresh = 60;
	int ret;

	ctx = devm_drm_panel_alloc(dev, struct m2468_panel, panel,
				   &m2468_panel_funcs,
				   DRM_MODE_CONNECTOR_DSI);
	if (IS_ERR(ctx))
		return PTR_ERR(ctx);

	ctx->dsi = dsi;

	/* 默认 REAL；DT 里写 meizu,panel-mode = "fake" 可切换 */
	/* 默认 FAKE：只注册 card0，不发 DSI 命令。DT 写 meizu,panel-mode 可覆盖 */
	ctx->mode = M2468_MODE_REAL;
	if (!of_property_read_string(dev->of_node, "meizu,panel-mode", &mode_str)) {
		if (!strcmp(mode_str, "fake"))
			ctx->mode = M2468_MODE_FAKE;
	}

	of_property_read_u32(dev->of_node, "meizu,panel-vrefresh", &vrefresh);

	ret = of_property_match_string(dev->of_node,
				       "regulator-names", "vddio");
	if (ret < 0)
		ret = 0;

	ctx->vddio = devm_regulator_get_optional(dev, "vddio");
	if (IS_ERR(ctx->vddio)) {
		ret = PTR_ERR(ctx->vddio);
		if (ret != -ENODEV)
			return dev_err_probe(dev, ret, "vddio\n");
		ctx->vddio = NULL;
	}

	ctx->vdd = devm_regulator_get_optional(dev, "vdd");
	if (IS_ERR(ctx->vdd)) {
		ret = PTR_ERR(ctx->vdd);
		if (ret != -ENODEV)
			return dev_err_probe(dev, ret, "vdd\n");
		ctx->vdd = NULL;
	}

	ctx->vci = devm_regulator_get_optional(dev, "vci");
	if (IS_ERR(ctx->vci)) {
		ret = PTR_ERR(ctx->vci);
		if (ret != -ENODEV)
			return dev_err_probe(dev, ret, "vci\n");
		ctx->vci = NULL;
	}

	ctx->reset_gpio = devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_LOW);
	DRM_INFO("M2468 reset_gpio: ptr=%px is_err=%d of_node=%pOF\n",
		 ctx->reset_gpio, IS_ERR(ctx->reset_gpio), dev->of_node);
	if (IS_ERR(ctx->reset_gpio))
		return dev_err_probe(dev, PTR_ERR(ctx->reset_gpio), "reset gpio\n");
	if (!ctx->reset_gpio) {
		/* optional 静默失败时用 index 方式强制再试一次 */
		ctx->reset_gpio = devm_gpiod_get_index(dev, NULL, 0, GPIOD_OUT_LOW);
		DRM_INFO("M2468 reset_gpio fallback(index0): ptr=%px is_err=%d\n",
			 ctx->reset_gpio, IS_ERR(ctx->reset_gpio));
		if (IS_ERR(ctx->reset_gpio))
			ctx->reset_gpio = NULL;
	}

	ctx->panel.prepare_prev_first = true;

	ret = drm_panel_of_backlight(&ctx->panel);
	if (ret)
		return dev_err_probe(dev, ret, "backlight\n");
	ctx->backlight = ctx->panel.backlight;

	mipi_dsi_set_drvdata(dsi, ctx);

	ret = devm_drm_panel_add(dev, &ctx->panel);
	if (ret)
		return dev_err_probe(dev, ret, "failed to add panel\n");

	/*
	 * MIPI-DSI 参数 + attach。
	 * mipi_dsi_attach() -> host 的 dsi_host_attach() -> dsi_dev_attach()
	 * -> component_add(DSI)。缺这一步 DSI 永远不会成为 component，
	 * component master(DPU) 就永远等不到它，msm_drm_bind 不执行，无 card0。
	 */
	dsi->lanes = 4;
	/* 原厂 mdss-dsi-bpp = 30（10bpc），与 DSC bits_per_component=10 一致；
	 * 声明 RGB888(8bpc) 会让 DSC 输入位深与 PPS 不符。 */
	dsi->format = MIPI_DSI_FMT_RGB101010;
	/* 原厂 panel 是 command mode（xjmz_amoled_tianma_cmd，带 TE gpio86），
	 * 不是 video mode。设 VIDEO 会让 msm 走 video 路径：
	 * 初始化命令能发进去，但像素帧到不了 panel 内部 GRAM，屏幕全黑。 */
	/* 原厂 cmd-mode 是 2 slices/packet（ROUTE-F/ROUTE-G 双证）；
	 * mainline 默认 slice_per_pkt=1 -> wc=633/pkt_per_line=2；
	 * 加此 flag -> wc=1265/pkt_per_line=1，复刻原厂包化。
	 * 只加这一个：NO_EOT_PACKET / CLOCK_NON_CONTINUOUS 是 BOE 屏的 PHY 参数，
	 * m2468 是天马 U8 LTPO，这两项不适用。 */
	/* E58: 对齐魅族20（boe-meizu20，同一战役已打赢）—— 改用
	 * NO_EOT_PACKET + CLOCK_NON_CONTINUOUS，去掉 LPM。
	 * 原注释断言这两项"不适用"，属未验证推断。 */
	/*
	 * E70: cmd mode -> video mode。
	 * 参照 sheng（小米平板 6S Pro，SM8550 + 天马面板 + DSC 双 slice）的配置：
	 * video mode 由硬件持续推流，扫描与传输天然锁定，不存在 cmd mode 那种
	 * 「写指针追上读指针」的撕裂；代价是 LTPO 自刷新失效（锁屏也会持续推流）。
	 */
	/* cmd mode（不是 video）。E70 试过 MIPI_DSI_MODE_VIDEO |
	 * MIPI_DSI_MODE_VIDEO_BURST，面板报
	 * "wait for video done timed out" 后黑屏 —— ILI7838E 是 cmd-only
	 * 面板，硬件上不接受连续视频流。已回滚。
	 */
	dsi->mode_flags = MIPI_DSI_MODE_NO_EOT_PACKET |
			  MIPI_DSI_CLOCK_NON_CONTINUOUS |
			  MIPI_DSI_MODE_DSC_ALL_SLICES_IN_PKT;
	/* 原厂 panel-clockrate = 0x41351d80 = 1094 Mbps（entry9 四档同值）。
	 * 不设的话 dsi_host.c:676 走默认时钟，带宽算错 ->
	 * DSI_ERR_STATE_FIFO | MDP_FIFO_UNDERFLOW (status=0xc)。 */
	dsi->hs_rate = 1200000000;

	/* ---- DSC: 面板初始化序列 #17 已发 PPS，进入 DSC 解码模式；
	 * 主机侧必须同样开 DSC，否则 panel 收到未压缩码流直接不输出
	 * （表现为"零 DSI 错误但纯黑"）。参数由原厂 dtbo PPS 逐字段解出。
	 * 必须在 mipi_dsi_attach() 之前填好，dsi_host_attach() 是唯一消费点。 */
	memset(&ctx->dsc, 0, sizeof(ctx->dsc));
	ctx->dsc.dsc_version_major  = 1;
	ctx->dsc.dsc_version_minor  = 2;
	ctx->dsc.bits_per_pixel     = 128;	/* 8.0 bpp << 4 */
	ctx->dsc.bits_per_component = 10;
	ctx->dsc.line_buf_depth     = 11;
	ctx->dsc.block_pred_enable  = 0;
	ctx->dsc.convert_rgb        = 1;
	ctx->dsc.simple_422         = 0;
	ctx->dsc.native_420         = 0;
	ctx->dsc.native_422         = 0;
	ctx->dsc.vbr_enable         = 0;
	ctx->dsc.slice_count        = 2;
	ctx->dsc.slice_width        = 632;
	ctx->dsc.slice_height       = 10;
	ctx->dsc.pic_width          = 1264;
	ctx->dsc.pic_height         = 2780;
	dsi->dsc = &ctx->dsc;
	DRM_INFO("DSC enabled: 8bpp/10bpc/%dx%d slice %dx%d count=%d\n",
		 ctx->dsc.pic_width, ctx->dsc.pic_height,
		 ctx->dsc.slice_width, ctx->dsc.slice_height, ctx->dsc.slice_count);

	ret = mipi_dsi_attach(dsi);
	if (ret)
		return dev_err_probe(dev, ret, "failed to attach to dsi host\n");

	dev_info(dev,
		 "ILI7838E panel registered: 1264x2780 mode=%s (clock %u kHz)\n",
		 ctx->mode == M2468_MODE_REAL ? "REAL" : "FAKE",
		 m2468_modes[0].clock);
	return 0;
}

static void m2468_remove(struct mipi_dsi_device *dsi)
{
	mipi_dsi_detach(dsi);
	struct m2468_panel *ctx = mipi_dsi_get_drvdata(dsi);

	m2468_unprepare(&ctx->panel);
}

static const struct of_device_id m2468_of_match[] = {
	{ .compatible = "meizu,m2468-panel" },
	{ }
};
MODULE_DEVICE_TABLE(of, m2468_of_match);

static struct mipi_dsi_driver m2468_driver = {
	.probe = m2468_probe,
	.remove = m2468_remove,
	.driver = {
		.name = "panel-meizu-m2468",
		.of_match_table = m2468_of_match,
	},
};
module_mipi_dsi_driver(m2468_driver);

MODULE_AUTHOR("m2468 bring-up");
MODULE_DESCRIPTION("Tianma ILI7838E AMOLED panel for Meizu 21 Note (m2468)");
MODULE_LICENSE("GPL");
