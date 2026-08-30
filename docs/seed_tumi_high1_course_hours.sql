-- 兔咪（tenant_id=7）高一年级 1-10 班课程与课时导入
-- 来源：2026-2027 学年度上学期任课教师安排表
-- 课时分别记录“工作日课时”和“周六课时”；晚课由晚自习规则单独安排。
-- 本脚本不写入教师任教关系；原表未标明 0.5 课时的单双周，当前按交替分配录入：
-- 音乐/心理/班会为单周，美术/校本/生涯为双周。

BEGIN;

DO $$
BEGIN
    IF (SELECT COUNT(*) FROM class WHERE tenant_id = 7 AND id BETWEEN 627 AND 636) <> 10 THEN
        RAISE EXCEPTION '目标班级不完整：租户7下应存在ID 627-636的高一1-10班';
    END IF;
END $$;

-- 所有科目都归属于兔咪租户，避免依赖跨租户公共科目。
INSERT INTO subject (tenant_id, name, evening_study_allowed)
SELECT 7, source.name, FALSE
FROM (VALUES
    ('语文'), ('数学'), ('英语'), ('物理'), ('化学'), ('生物'),
    ('政治'), ('历史'), ('地理'), ('体育'),
    ('音乐'), ('美术'), ('心理'), ('校本'), ('班会'), ('生涯')
) AS source(name)
WHERE NOT EXISTS (
    SELECT 1 FROM subject existing
    WHERE existing.tenant_id = 7 AND existing.name = source.name
);

-- 完整周课时 = 工作日 + 周六 + 晚课。
WITH source_hours(
    name, weekday_periods, saturday_periods, week_parity,
    evening_periods_odd, evening_periods_even
) AS (
    VALUES
        ('语文', 5.0, 1.0, 'all', 1, 1),
        ('数学', 6.0, 1.0, 'all', 1, 1),
        ('英语', 5.0, 1.0, 'all', 1, 1),
        ('物理', 3.0, 1.0, 'all', 1, 0),
        ('化学', 3.0, 0.5, 'all', 1, 0),
        ('生物', 3.0, 0.5, 'all', 1, 0),
        ('历史', 3.0, 1.0, 'all', 0, 1),
        ('政治', 2.0, 0.5, 'all', 0, 1),
        ('地理', 3.0, 0.5, 'all', 0, 1),
        ('体育', 2.0, 0.0, 'all', 0, 0),
        ('音乐', 0.5, 0.0, 'odd', 0, 0),
        ('美术', 0.5, 0.0, 'even', 0, 0),
        ('心理', 0.5, 0.0, 'odd', 0, 0),
        ('校本', 0.5, 0.0, 'even', 0, 0),
        ('班会', 0.5, 0.0, 'odd', 0, 0),
        ('生涯', 0.5, 0.0, 'even', 0, 0)
), resolved_subjects AS (
    SELECT DISTINCT ON (source_hours.name)
        source_hours.name,
        subject.id AS subject_id,
        source_hours.weekday_periods,
        source_hours.saturday_periods,
        source_hours.weekday_periods + source_hours.saturday_periods AS weekly_periods,
        source_hours.week_parity,
        source_hours.evening_periods_odd,
        source_hours.evening_periods_even
    FROM source_hours
    JOIN subject
      ON subject.name = source_hours.name
     AND subject.tenant_id = 7
    ORDER BY source_hours.name, (subject.tenant_id IS NULL) DESC, subject.id
)
INSERT INTO coursehourplan (
    tenant_id, class_id, subject_id, academic_year, term,
    weekday_periods, saturday_periods, weekly_periods, week_parity,
    evening_periods_odd, evening_periods_even
)
SELECT
    7,
    class.id,
    resolved_subjects.subject_id,
    '2026-2027',
    '1',
    resolved_subjects.weekday_periods,
    resolved_subjects.saturday_periods,
    resolved_subjects.weekly_periods,
    resolved_subjects.week_parity::weekparity,
    resolved_subjects.evening_periods_odd,
    resolved_subjects.evening_periods_even
FROM class
CROSS JOIN resolved_subjects
WHERE class.tenant_id = 7
  AND class.id BETWEEN 627 AND 636
ON CONFLICT (tenant_id, academic_year, term, class_id, subject_id, week_parity)
DO UPDATE SET
    weekday_periods = EXCLUDED.weekday_periods,
    saturday_periods = EXCLUDED.saturday_periods,
    weekly_periods = EXCLUDED.weekly_periods,
    evening_periods_odd = EXCLUDED.evening_periods_odd,
    evening_periods_even = EXCLUDED.evening_periods_even;

COMMIT;
