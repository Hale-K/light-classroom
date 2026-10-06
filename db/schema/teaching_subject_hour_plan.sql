-- PostgreSQL；可重复执行。仅新增课时方案及教学班来源字段，不修改既有课时/排课。
CREATE TABLE IF NOT EXISTS teaching_subject_hour_plan (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    grade_id INTEGER NOT NULL REFERENCES grade(id) ON DELETE RESTRICT,
    subject_id INTEGER NOT NULL REFERENCES subject(id) ON DELETE RESTRICT,
    academic_year VARCHAR(20) NOT NULL,
    term VARCHAR(20) NOT NULL,
    weekly_periods INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_teaching_subject_hour_plan_scope UNIQUE (tenant_id, grade_id, academic_year, term, subject_id),
    CONSTRAINT ck_teaching_subject_hours_range CHECK (weekly_periods BETWEEN 1 AND 12),
    CONSTRAINT ck_teaching_subject_hours_term CHECK (term IN ('1', '2'))
);
CREATE INDEX IF NOT EXISTS ix_teaching_subject_hour_plan_tenant_id ON teaching_subject_hour_plan(tenant_id);
CREATE INDEX IF NOT EXISTS ix_teaching_subject_hour_plan_grade_id ON teaching_subject_hour_plan(grade_id);
CREATE INDEX IF NOT EXISTS ix_teaching_subject_hour_plan_subject_id ON teaching_subject_hour_plan(subject_id);
CREATE INDEX IF NOT EXISTS ix_teaching_subject_hour_plan_academic_year ON teaching_subject_hour_plan(academic_year);
ALTER TABLE teachingclass ADD COLUMN IF NOT EXISTS hour_plan_id INTEGER REFERENCES teaching_subject_hour_plan(id) ON DELETE SET NULL;
ALTER TABLE teachingclass ADD COLUMN IF NOT EXISTS hours_overridden BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_teachingclass_hour_plan_id ON teachingclass(hour_plan_id);
COMMENT ON TABLE teaching_subject_hour_plan IS '走班科目课时方案：学校/年级/学年/学期/科目唯一';
COMMENT ON COLUMN teachingclass.hour_plan_id IS '来源科目课时方案；历史教学班允许为空';
COMMENT ON COLUMN teachingclass.hours_overridden IS '是否单独调整课时；weekly_periods保存教学班实际课时';
