from pathlib import Path
p=Path('backend/app/ai/tools/clarification.py');s=p.read_text(encoding='utf-8').replace('先补充关键决策，我会保留','先补充具体的关键决策，我会保留');p.write_text(s,encoding='utf-8')
