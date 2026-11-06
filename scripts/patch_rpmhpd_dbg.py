import io
p = "/home/shrp/lmp73/drivers/pmdomain/qcom/rpmhpd.c"
s = io.open(p, encoding="utf-8").read()

old_on = ("\tcorner = max(pd->corner, pd->enable_corner);\n"
          "\t/* m2468: honour the cx floor (see rpmhpd_floor_corner) */\n"
          "\tcorner = max(corner, (unsigned int)rpmhpd_floor_corner(pd));\n")
new_on = ("\tcorner = max(pd->corner, pd->enable_corner);\n"
          "\t/* m2468: honour the cx floor (see rpmhpd_floor_corner) */\n"
          "\tcorner = max(corner, (unsigned int)rpmhpd_floor_corner(pd));\n"
          "\tpr_info(\"m2468-poweron %s corner=%u lc=%d ec=%d\",\n"
          "\t\tpd->pd.name, corner, pd->level_count, pd->enable_corner);\n")
assert old_on in s, "power_on hunk missing"
s = s.replace(old_on, new_on, 1)

old_set = ("\t\t/* m2468: honour the cx floor (see rpmhpd_floor_corner) */\n"
           "\t\tif (i < rpmhpd_floor_corner(pd))\n"
           "\t\t\ti = rpmhpd_floor_corner(pd);\n")
new_set = ("\t\t/* m2468: honour the cx floor (see rpmhpd_floor_corner) */\n"
           "\t\tif (i < rpmhpd_floor_corner(pd))\n"
           "\t\t\ti = rpmhpd_floor_corner(pd);\n"
           "\t\tpr_info(\"m2468-setperf %s i=%d lc=%d\",\n"
           "\t\t\tpd->pd.name, i, pd->level_count);\n")
assert old_set in s, "set_perf hunk missing"
s = s.replace(old_set, new_set, 1)

io.open(p, "w", encoding="utf-8").write(s)
print("diagnostics added")
