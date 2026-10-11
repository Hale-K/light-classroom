"""Minimal SQL seed for the explicitly selected school, leaving courses to the Agent."""
import asyncio
import csv
import getpass
import io
import json
import os
from pathlib import Path
import re
import sys

import bcrypt
import openpyxl
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.chdir(ROOT / 'backend')
from app.core.config import settings

school_code = 'hengshui'
year = '2026-2027'
sheet = openpyxl.load_workbook(r'E:\school\class\高一教师课时.xlsx', data_only=True).worksheets[0]
teachers = []
subject = None
for row in sheet.iter_rows(min_row=2, values_only=True):
    if row[0]: subject = str(row[0]).strip()
    classes = str(row[3] or '')
    if re.fullmatch(r'\d+-\d+', classes):
        start, end = map(int, classes.split('-'))
        numbers = list(range(start, end + 1))
    else:
        numbers = [int(v) for v in re.findall(r'\d+', classes)]
    if 1 not in numbers: continue
    name = re.sub(r'\s+', '', str(row[2]).lstrip('*').strip())
    teachers.append({'name': name, 'subject': subject, 'account': f'hengshui_t{int(row[1]):03d}'})
if len(teachers) != 13 or len({t['name'] for t in teachers}) != 13:
    raise RuntimeError('Workbook selection changed; stop for review')

password = os.environ.get('LIGHT_SEED_PASSWORD') or getpass.getpass('Initial teacher password: ')
for teacher in teachers:
    teacher['hash'] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
del password
payload = json.dumps(teachers, ensure_ascii=False).replace("'", "''")
sql = """DO $seed$
DECLARE
 t integer; g integer; gu integer; su integer; sg integer; uid integer;
 cp integer; bd integer; rm integer; cl integer; rec jsonb;
BEGIN
 SELECT id INTO STRICT t FROM tenant WHERE code='hengshui' AND name='衡水中学';
 PERFORM id FROM tenant WHERE id=t FOR UPDATE;
 IF NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id=t AND phone='15070480960' AND role='director') THEN
  RAISE EXCEPTION 'School principal mismatch';
 END IF;
 SELECT id INTO STRICT g FROM grade WHERE tenant_id=t AND name='高一年级';
 SELECT id INTO gu FROM organizationunit WHERE tenant_id=t AND unit_type='grade_group' AND grade_id=g AND academic_year='2026-2027';
 IF gu IS NULL THEN
  INSERT INTO organizationunit(tenant_id,created_at,updated_at,name,unit_type,grade_id,academic_year,cohort_label,sort_order,status)
  VALUES(t,now(),now(),'高一年级部','grade_group',g,'2026-2027','2026',1,'active') RETURNING id INTO gu;
 END IF;
 FOR rec IN SELECT value FROM jsonb_array_elements('__PAYLOAD__'::jsonb) LOOP
  SELECT id INTO su FROM subject WHERE tenant_id=t AND name=rec->>'subject';
  IF su IS NULL THEN
   INSERT INTO subject(tenant_id,name,course_type,evening_study_allowed) VALUES(t,rec->>'subject','subject',false) RETURNING id INTO su;
  END IF;
  SELECT id INTO sg FROM organizationunit WHERE tenant_id=t AND parent_id=gu AND unit_type='subject_group' AND subject_id=su;
  IF sg IS NULL THEN
   INSERT INTO organizationunit(tenant_id,created_at,updated_at,parent_id,name,unit_type,subject_id,academic_year,cohort_label,sort_order,status)
   VALUES(t,now(),now(),gu,(rec->>'subject')||'组','subject_group',su,'2026-2027','2026',1,'active') RETURNING id INTO sg;
  END IF;
  IF EXISTS(SELECT 1 FROM "user" WHERE tenant_id=t AND phone=rec->>'account' AND name<>rec->>'name') THEN
   RAISE EXCEPTION 'Existing account belongs to another teacher';
  END IF;
  IF (SELECT count(*) FROM "user" WHERE tenant_id=t AND name=rec->>'name')>1 THEN
   RAISE EXCEPTION 'Ambiguous teacher name';
  END IF;
  SELECT id INTO uid FROM "user" WHERE tenant_id=t AND name=rec->>'name';
  IF uid IS NULL THEN
   INSERT INTO "user"(tenant_id,created_at,updated_at,name,phone,password_hash,role,status,frozen)
   VALUES(t,now(),now(),rec->>'name',rec->>'account',rec->>'hash','teacher','active',false) RETURNING id INTO uid;
  END IF;
  IF NOT EXISTS(SELECT 1 FROM staffappointment WHERE tenant_id=t AND organization_unit_id=sg AND staff_id=uid AND position_code='member' AND academic_year='2026-2027') THEN
   INSERT INTO staffappointment(tenant_id,created_at,updated_at,organization_unit_id,staff_id,position_code,academic_year,status)
   VALUES(t,now(),now(),sg,uid,'member','2026-2027','active');
  END IF;
 END LOOP;
 SELECT id INTO cp FROM campus WHERE tenant_id=t AND name='主校区';
 IF cp IS NULL THEN
  INSERT INTO campus(tenant_id,created_at,updated_at,name,status) VALUES(t,now(),now(),'主校区','active') RETURNING id INTO cp;
 END IF;
 SELECT id INTO bd FROM building WHERE tenant_id=t AND campus_id=cp AND name='教学楼';
 IF bd IS NULL THEN
  INSERT INTO building(tenant_id,created_at,updated_at,campus_id,name,floor_count,status) VALUES(t,now(),now(),cp,'教学楼',1,'active') RETURNING id INTO bd;
 END IF;
 SELECT id INTO rm FROM room WHERE tenant_id=t AND building_id=bd AND name='高一（1）班教室';
 IF rm IS NULL THEN
  INSERT INTO room(tenant_id,created_at,updated_at,building_id,name,code,floor,capacity,room_type,features,is_schedulable,is_exam_enabled,status)
  VALUES(t,now(),now(),bd,'高一（1）班教室','G1-01',1,40,'classroom','[]'::json,true,false,'available') RETURNING id INTO rm;
 END IF;
 SELECT id INTO cl FROM class WHERE tenant_id=t AND grade_id=g AND academic_year='2026-2027' AND term='1' AND name='高一（1）班';
 IF cl IS NULL THEN
  INSERT INTO class(tenant_id,grade_id,academic_year,term,campus_id,home_room_id,class_type,name,cohort_label)
  VALUES(t,g,'2026-2027','1',cp,rm,'regular','高一（1）班','2026') RETURNING id INTO cl;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM organizationunit WHERE tenant_id=t AND parent_id=gu AND unit_type='admin_class' AND name='高一（1）班') THEN
  INSERT INTO organizationunit(tenant_id,created_at,updated_at,parent_id,name,unit_type,academic_year,cohort_label,sort_order,status)
  VALUES(t,now(),now(),gu,'高一（1）班','admin_class','2026-2027','2026',1,'active');
 END IF;
END $seed$;
""".replace('__PAYLOAD__', payload)
out = ROOT / 'output/agent-school-seed'
out.mkdir(parents=True, exist_ok=True)
(out / 'hengshui-minimal.sql').write_text(sql, encoding='utf-8')
with (out / 'teacher-accounts.csv').open('w', encoding='utf-8-sig', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(['教师', '科目', '登录账号'])
    writer.writerows((t['name'], t['subject'], t['account']) for t in teachers)

async def main():
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            raw = await connection.get_raw_connection()
            await raw.driver_connection.execute(sql)
        print('Committed minimal school seed: 13 teachers, grade/subject groups, one class and one classroom. Course hours and teaching assignments untouched.')
    finally:
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
