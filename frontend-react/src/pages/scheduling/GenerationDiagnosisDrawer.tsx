import { App, Button, Drawer, Space, Tag } from "antd";
import { useState } from "react";
import { schedulingApi } from "@/api";
import {
  DEFAULT_GEN_PIPELINE,
  type GenerationAuditState,
  type GenerationSuggestion,
} from "./scheduling-model";

type Props = {
  open: boolean;
  onClose: () => void;
  generation: GenerationAuditState;
  academicYear: string;
  term: string;
  onRetryGenerate?: () => void;
  onGoHours?: () => void;
  onOpenRules?: (groupId?: string) => void;
  onSuggestionApplied?: () => void;
};

export default function GenerationDiagnosisDrawer({
  open,
  onClose,
  generation,
  academicYear,
  term,
  onRetryGenerate,
  onGoHours,
  onOpenRules,
  onSuggestionApplied,
}: Props) {
  const { message } = App.useApp();
  const [applyingKey, setApplyingKey] = useState<string | null>(null);

  const applySuggestion = async (suggestion: GenerationSuggestion) => {
    if (suggestion.action === "check_hours") {
      onGoHours?.();
      return;
    }
    if (!suggestion.applicable && suggestion.action !== "demote_to_soft") {
      message.info("请按说明手工调整该建议");
      return;
    }
    const groupId = generation.groupId || generation.diagnosis?.rule_group_id;
    if (!groupId) {
      message.warning("找不到对应的综合规则，请到「建立规则」中手工调整");
      return;
    }
    const key = `${suggestion.rule_id}:${suggestion.action}`;
    setApplyingKey(key);
    try {
      const result = await schedulingApi.applyRuleSuggestion({
        academic_year: academicYear,
        term,
        group_id: groupId,
        suggestion: {
          rule_id: suggestion.rule_id,
          action: suggestion.action,
          param_patch: suggestion.param_patch ?? undefined,
        },
      });
      message.success(result.note || "已应用建议");
      onSuggestionApplied?.();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "应用建议失败");
    } finally {
      setApplyingKey(null);
    }
  };

  const pipeline =
    generation.diagnosis?.pipeline?.length
      ? generation.diagnosis.pipeline
      : [...DEFAULT_GEN_PIPELINE];
  const stuck =
    generation.diagnosis?.stuck_step ||
    generation.trace[generation.trace.length - 1]?.phase ||
    generation.stage;
  const stuckIndex = Math.max(
    0,
    pipeline.findIndex((step) => step.id === stuck),
  );

  return (
    <Drawer
      title={
        generation.diagnosis
          ? "排课失败诊断"
          : generation.generating
            ? "排课过程"
            : "排课过程"
      }
      placement="right"
      width={420}
      open={open}
      onClose={onClose}
      zIndex={1100}
      destroyOnClose={false}
      maskClosable={!generation.generating}
      extra={
        <Space>
          <Button
            size="small"
            onClick={() =>
              onOpenRules?.(
                generation.groupId ||
                  generation.diagnosis?.rule_group_id ||
                  undefined,
              )
            }
          >
            去改规则
          </Button>
        </Space>
      }
    >
      <div className="sk-gen-drawer">
        <ol className="rule-group-audit-pipeline">
          {pipeline.map((step, index) => {
            const isStuck =
              Boolean(generation.diagnosis) && step.id === stuck;
            const isDone =
              !isStuck &&
              (generation.stage === "done" || index < stuckIndex);
            const isActive =
              !generation.diagnosis &&
              (step.id === stuck ||
                (generation.generating && index === stuckIndex));
            return (
              <li
                key={step.id}
                className={[
                  isDone ? "is-done" : "",
                  isActive ? "is-active" : "",
                  isStuck ? "is-stuck" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <i aria-hidden="true">
                  {isStuck ? "!" : isDone ? "✓" : index + 1}
                </i>
                <span>{step.label}</span>
              </li>
            );
          })}
        </ol>

        {generation.diagnosis?.stuck_label ? (
          <div className="rule-group-audit-stuck">
            {generation.diagnosis.stuck_label}
          </div>
        ) : null}

        {generation.summary ? (
          <p className="rule-group-audit-process-summary">
            {generation.summary}
            {generation.generating
              ? ` · ${Math.round(generation.percent)}% · ${Math.floor(generation.elapsed)}s`
              : ""}
          </p>
        ) : (
          <p className="rule-group-audit-process-empty">
            从「日课表」发起生成后，求解步骤与建议会出现在这里。
          </p>
        )}

        {generation.trace.length > 0 ? (
          <ul className="rule-group-audit-trace">
            {generation.trace.slice(-16).map((item, index) => (
              <li key={`${item.ts || 0}-${index}`}>
                <span>{item.phase || item.stage || "—"}</span>
                <em>{item.message || ""}</em>
              </li>
            ))}
          </ul>
        ) : null}

        {generation.diagnosis?.reasons?.length ? (
          <div className="rule-group-audit-reasons">
            <strong>失败原因</strong>
            <ul>
              {generation.diagnosis.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {generation.diagnosis?.suggestions?.length ? (
          <div className="rule-group-audit-suggestions">
            <strong>推荐修改</strong>
            <ul>
              {generation.diagnosis.suggestions.map((item, index) => {
                const key = `${item.rule_id}:${item.action}:${index}`;
                const canApply =
                  item.action === "check_hours" || item.applicable !== false;
                return (
                  <li key={key}>
                    <div>
                      <b>
                        {item.rule_id ? `${item.rule_id} · ` : ""}
                        {item.title}
                      </b>
                      <Tag>{item.action_label || item.action}</Tag>
                    </div>
                    <p>{item.reason}</p>
                    <small>{item.impact}</small>
                    {canApply ? (
                      <Button
                        size="small"
                        type="primary"
                        ghost
                        loading={
                          applyingKey === `${item.rule_id}:${item.action}`
                        }
                        disabled={Boolean(generation.generating)}
                        onClick={() => void applySuggestion(item)}
                      >
                        {item.action === "check_hours"
                          ? "去课时管理"
                          : "应用建议"}
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

        <div style={{ marginTop: 16 }}>
          {onRetryGenerate ? (
            <Button
              block
              type="primary"
              disabled={Boolean(generation.generating)}
              onClick={() => onRetryGenerate()}
            >
              按当前规则重新生成
            </Button>
          ) : null}
          <Button block style={{ marginTop: 8 }} onClick={onClose}>
            关闭
          </Button>
        </div>
      </div>
    </Drawer>
  );
}
