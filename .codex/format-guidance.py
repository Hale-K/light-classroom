from pathlib import Path
p=Path('frontend-react/src/components/AssistantDock.tsx');s=p.read_text(encoding='utf-8').replace('        model_visible: item.modelVisible !== false,\n          clarification: item.clarification,','        model_visible: item.modelVisible !== false,\n        clarification: item.clarification,');p.write_text(s,encoding='utf-8')
