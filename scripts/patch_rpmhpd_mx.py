import io
p = "/home/shrp/lmp73/drivers/pmdomain/qcom/rpmhpd.c"
s = io.open(p, encoding="utf-8").read()

old = '''static int rpmhpd_floor_corner(struct rpmhpd *pd)
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
}'''

new = '''/*
 * Android gives the modem both cx (corner 384 == TURBO) and mx (corner 320 ==
 * NOM_L1) supplies via cx-supply / mx-supply plus cx-uV-uA / mx-uV-uA.
 * Mainline has neither, so floor both domains.  Values are RPMh corner numbers;
 * 0 disables the floor for that domain.
 */
static unsigned int rpmhpd_mx_min_level __read_mostly = 320;
module_param_named(mx_min_level, rpmhpd_mx_min_level, uint, 0644);
MODULE_PARM_DESC(mx_min_level, "minimum RPMh corner for the mx power domain");

static int rpmhpd_floor_corner(struct rpmhpd *pd)
{
\tunsigned int floor;
\tint i;

\tif (!pd->level_count)
\t\treturn 0;

\tif (!strcmp(pd->pd.name, "cx"))
\t\tfloor = rpmhpd_cx_min_level;
\telse if (!strcmp(pd->pd.name, "mx"))
\t\tfloor = rpmhpd_mx_min_level;
\telse
\t\treturn 0;

\tif (!floor)
\t\treturn 0;

\tfor (i = 0; i < pd->level_count; i++)
\t\tif ((int)floor <= pd->level[i])
\t\t\treturn i;

\treturn pd->level_count - 1;
}'''

assert old in s, "floor helper not found"
s = s.replace(old, new, 1)
io.open(p, "w", encoding="utf-8").write(s)
print("mx floor added")
