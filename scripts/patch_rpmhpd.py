import io
p = "/home/shrp/lmp73/drivers/pmdomain/qcom/rpmhpd.c"
s = io.open(p, encoding="utf-8").read()

# --- 1. insert the floor helper right after the global lock definition ---
anchor = "static DEFINE_MUTEX(rpmhpd_lock);\n"
assert anchor in s, "lock anchor not found"

helper = anchor + """
/*
 * m2468: Android keeps the cx rail at or above TURBO (RPMh corner 384) through a
 * proxy consumer on the "cx.lvl" arc regulator (qcom,rpmh-arc-regulator with
 * qcom,proxy-consumer-enable / qcom,proxy-consumer-voltage = <0x180 0xffff>).
 *
 * Mainline models cx only as an rpmhpd power domain, and on this device the
 * modem's proxy device never actually votes (genpd:0:4080000.remoteproc stays
 * runtime-suspended with performance state 0), so cx settles at LOW_SVS (64).
 * The modem firmware then asserts while bringing its PLL back out of power
 * collapse:
 *   mcpm_resrc_modem_pll.c:1213: Assertion clk_mpss_req_status == CLOCK_SUCCESS failed
 * resulting in a ~30-40 s crash loop whenever the radio is up.
 *
 * Enforce a floor for the cx domain only.  rpmhpd_cx_min_level is the RPMh
 * corner value (384 == RPMH_REGULATOR_LEVEL_TURBO); set it to 0 to disable.
 */
static unsigned int rpmhpd_cx_min_level __read_mostly = 384;
module_param_named(cx_min_level, rpmhpd_cx_min_level, uint, 0644);
MODULE_PARM_DESC(cx_min_level, "minimum RPMh corner for the cx power domain");

static int rpmhpd_floor_corner(struct rpmhpd *pd)
{
\tint i;

\tif (!rpmhpd_cx_min_level || !pd->level_count)
\t\treturn 0;
\tif (strcmp(pd->pd.name, "cx"))
\t\treturn 0;

\tfor (i = 0; i < pd->level_count; i++)
\t\tif ((int)rpmhpd_cx_min_level <= pd->level[i])
\t\t\treturn i;

\treturn pd->level_count - 1;
}
"""
s = s.replace(anchor, helper, 1)

# --- 2. clamp the corner used when powering a domain on ---
old_on = "\tcorner = max(pd->corner, pd->enable_corner);\n\tret = rpmhpd_aggregate_corner(pd, corner);"
new_on = ("\tcorner = max(pd->corner, pd->enable_corner);\n"
          "\t/* m2468: honour the cx floor (see rpmhpd_floor_corner) */\n"
          "\tcorner = max(corner, (unsigned int)rpmhpd_floor_corner(pd));\n"
          "\tret = rpmhpd_aggregate_corner(pd, corner);")
assert old_on in s, "power_on body not found"
s = s.replace(old_on, new_on, 1)

# --- 3. clamp explicit performance-state requests too ---
old_set = ("\tif (pd->enabled) {\n"
           "\t\t/* Ensure that the domain isn't turn off */\n"
           "\t\tif (i < pd->enable_corner)\n"
           "\t\t\ti = pd->enable_corner;\n")
new_set = ("\tif (pd->enabled) {\n"
           "\t\t/* Ensure that the domain isn't turn off */\n"
           "\t\tif (i < pd->enable_corner)\n"
           "\t\t\ti = pd->enable_corner;\n"
           "\t\t/* m2468: honour the cx floor (see rpmhpd_floor_corner) */\n"
           "\t\tif (i < rpmhpd_floor_corner(pd))\n"
           "\t\t\ti = rpmhpd_floor_corner(pd);\n")
assert old_set in s, "set_performance_state body not found"
s = s.replace(old_set, new_set, 1)

io.open(p, "w", encoding="utf-8").write(s)
print("rpmhpd.c patched")
