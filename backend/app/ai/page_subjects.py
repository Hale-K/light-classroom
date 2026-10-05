"""Validate the subject form before handing a task to the in-page agent."""
import re

from pydantic import BaseModel, Field


class SubjectDraft(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    course_type: str | None = Field(default=None, max_length=30)
    evening_study_allowed: bool | None = None


def explicit_subject_draft(content: str, previous: SubjectDraft) -> SubjectDraft | None:
    """Resolve unambiguous form input without a model round trip."""
    name = re.search(r'(?:科目名称|名称|名字)\s*(?:是|叫|为|[:：])\s*[“「"\']([^”」"\']+)[”」"\']', content)
    if not name:
        name = re.search(r'(?:科目名称|名称|名字)\s*(?:是|叫|为|[:：])\s*([^，,。\n：:]+?)(?=\s+(?:科目|课程)类型|[，,。\n]|$)', content)
    # Only reuse a name for a message composed entirely of form choices.
    choices_only = re.fullmatch(r'[\s，,。]*(?:(?:课程|科目)类型(?:是|为|[:：])?\s*)?(?:学科课|活动课)?[\s，,。]*(?:(?:晚自习资格[:：]?\s*)?(?:不允许|允许)(?:参加)?(?:晚自习)?(?:资格)?)[\s，,。]*|[\s，,。]*(?:学科课|活动课)[\s，,。]*', content)
    if not name and not (previous.name and choices_only):
        return None
    result = previous.model_copy()
    if name:
        result.name = name[1].strip()
    return result


def validate_subject_draft(draft: SubjectDraft, existing_names: list[str]) -> dict:
    values = draft.model_dump()
    values['name'] = (draft.name or '').strip()
    missing = []
    if not values['name'] or len(values['name']) > 20:
        missing.append('name')
    if draft.course_type not in ('subject', 'activity'):
        missing.append('course_type')
    if draft.evening_study_allowed is None:
        missing.append('evening_study_allowed')
    if missing:
        return {
            'status': 'needs_input', 'draft': values, 'missing': missing,
            'text': '还需要你明确提供：\n' + '\n'.join({
                'name': '• 科目名称（1～20 个字）',
                'course_type': '• 课程类型：学科课还是活动课？',
                'evening_study_allowed': '• 晚自习资格：允许还是不允许？',
            }[field] for field in missing),
        }
    if values['name'] in existing_names:
        return {'status': 'exists', 'draft': values, 'missing': [],
                'text': f'「{values["name"]}」已存在，无需重复创建。'}
    return {'status': 'ready', 'draft': values, 'missing': [],
            'text': f'数据校验通过，准备新增「{values["name"]}」。'}
