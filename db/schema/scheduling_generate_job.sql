-- 排课生成任务持久化：用于服务重启续跑与 MQ 重投幂等。
CREATE TABLE IF NOT EXISTS scheduling_generate_job (
    id varchar(32) PRIMARY KEY,
    tenant_id integer NOT NULL,
    academic_year varchar(20) NOT NULL,
    term varchar(20) NOT NULL,
    payload json NOT NULL DEFAULT '{}'::json,
    status varchar(20) NOT NULL DEFAULT 'queued',
    stage varchar(30) NOT NULL DEFAULT 'queued',
    message varchar(300) NOT NULL DEFAULT '已进入排课队列',
    percent integer NOT NULL DEFAULT 0,
    attempt integer NOT NULL DEFAULT 0,
    result json,
    error json,
    created_at timestamp NOT NULL DEFAULT now(),
    updated_at timestamp NOT NULL DEFAULT now(),
    heartbeat_at timestamp NOT NULL DEFAULT now(),
    finished_at timestamp
);

CREATE INDEX IF NOT EXISTS ix_scheduling_generate_job_tenant_id
    ON scheduling_generate_job (tenant_id);
CREATE INDEX IF NOT EXISTS ix_scheduling_generate_job_academic_year
    ON scheduling_generate_job (academic_year);
CREATE INDEX IF NOT EXISTS ix_scheduling_generate_job_term
    ON scheduling_generate_job (term);
CREATE INDEX IF NOT EXISTS ix_scheduling_generate_job_status
    ON scheduling_generate_job (status);
CREATE INDEX IF NOT EXISTS ix_scheduling_generate_job_scope_status
    ON scheduling_generate_job (tenant_id, academic_year, term, status);
