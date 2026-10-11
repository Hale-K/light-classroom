from pathlib import Path
p=Path('frontend-react/src/components/AssistantClarificationCard.tsx');s=p.read_text(encoding='utf-8');s=s.replace('<input type="radio" name={q.id} checked={answers[q.id] === option}', '<input type="radio" aria-label={option} name={q.id} checked={answers[q.id] === option}');p.write_text(s,encoding='utf-8')
