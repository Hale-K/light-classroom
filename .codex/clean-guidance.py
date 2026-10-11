from pathlib import Path
p=Path('backend/app/ai/agent/assistant_agent.py');s=p.read_text(encoding='utf-8');a=s.index('# 意图确实无法归类');b=s.index('async def agent_reply',a);p.write_text(s[:a]+s[b:],encoding='utf-8')
