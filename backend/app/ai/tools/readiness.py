"""排课准备度检查：覆盖关系与课量，不冒充整体求解可行性。"""
from app.services.scheduling import has_scheduled_hours


def readiness_lines(classes, plans, assignments, subjects, grid):
    names = {c.id: c.name for c in classes}
    subject_names = {s.id: s.name for s in subjects}
    activities = {s.id for s in subjects if s.course_type == "activity"}
    plans = [p for p in plans if p.class_id in names and has_scheduled_hours(p.model_dump())]
    assignments = [a for a in assignments if a.class_id in names]
    assigned = {(a.class_id, a.subject_id): a for a in assignments}
    planned_classes = {p.class_id for p in plans}
    missing_classes = [name for cid, name in names.items() if cid not in planned_classes]
    missing_pairs = []
    empty_teachers = []
    for p in plans:
        label = f"{names[p.class_id]}·{subject_names.get(p.subject_id, '未找到的科目')}"
        a = assigned.get((p.class_id, p.subject_id))
        if a is None:
            missing_pairs.append(label)
        elif a.teacher_id is None and p.subject_id not in activities:
            empty_teachers.append(label)
    missing_pairs = list(dict.fromkeys(missing_pairs))
    empty_teachers = list(dict.fromkeys(empty_teachers))
    daily = grid.get("daily_periods") or []
    lines = [f"检查范围：{len(classes)} 个行政班；有课时方案 {len(planned_classes)} 个班。"]
    for title, values in [("未找到有效课时方案的班级", missing_classes), ("课时尚未匹配任教关系", missing_pairs), ("学科任教尚未指定教师", empty_teachers)]:
        lines.append(f"{title}：{len(values)} 项" + ("，" + "、".join(values[:8]) + ("（其余略）" if len(values) > 8 else "") if values else "") + "。")
    over = []
    if grid.get("configured"):
        lines.append("实际白天课位：" + "；".join(f"周{'一二三四五六日'[i]} {n} 节" for i, n in enumerate(daily)) + "。")
        over = []
        for cid, name in names.items():
            for parity in ("odd", "even"):
                applicable = [p for p in plans if p.class_id == cid and p.week_parity in ("all", parity)]
                for label, requested, capacity in [
                    ("工作日", sum(p.weekday_periods for p in applicable), sum(daily[:5])),
                    ("周六", sum(p.saturday_periods for p in applicable), daily[5] if len(daily) > 5 else 0),
                ]:
                    if requested > capacity:
                        over.append(f"{name}{'单' if parity == 'odd' else '双'}周{label} {requested:g}/{capacity} 节")
        lines.append(f"白天课量超容量：{len(over)} 项" + ("，" + "；".join(over[:8]) if over else "") + "。")
    else:
        lines.append("课位结构未保存，暂不能判断课量是否装得下。")
    if not classes:
        next_step = "先建立年级和行政班。"
    elif not grid.get("configured"):
        next_step = "先到课位结构保存本学期实际课位。"
    elif missing_classes:
        next_step = "先核对上述班级的课时方案；旧任教中的课量仅作兼容，不能据此认定方案已齐。"
    elif missing_pairs or empty_teachers:
        next_step = "先到任教关系补齐上述班科和教师。"
    elif over:
        next_step = "先调整上述班级的课量或实际课位，解决超容量后再做资源校验。"
    else:
        next_step = "到排课页做资源校验，再核对所选年级规则组；当前结果不代表可生成或无冲突。"
    lines.append("下一步：" + next_step)
    lines.append("尚未验证：教师是否停用/超负荷、晚课与单双周完整容量、规则相容性、求解可行性。")
    return lines
