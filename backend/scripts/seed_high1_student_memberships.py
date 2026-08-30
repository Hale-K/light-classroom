"""Idempotently seed high-school first-year students and cohort memberships."""

import argparse
import asyncio
from collections.abc import Iterable

from sqlmodel import select

from app.db.session import AsyncSessionLocal
from app.models.facility import Campus
from app.models.org import Grade, OrganizationUnit, Student, StudentGradeMembership, Tenant


SURNAME = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳酆鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴郁胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
GIVEN = "子涵宇轩浩然梓涵俊杰雨泽思远博文嘉豪明轩一鸣欣怡诗涵佳怡梦瑶可欣语嫣若曦心怡紫妍依诺晨曦沐阳泽宇睿哲昊然景行知远安然清妍书瑶雅静逸凡乐言承泽昕玥锦程亦辰嘉宁"


def unique_names(existing: Iterable[str]):
    used = set(existing)
    index = 0
    while True:
        surname = SURNAME[index % len(SURNAME)]
        given = GIVEN[(index // len(SURNAME)) % len(GIVEN)]
        name = surname + given
        index += 1
        if name not in used:
            used.add(name)
            yield name


async def main(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.code == args.school_code))).scalar_one_or_none()
        if not tenant:
            raise RuntimeError(f"学校不存在: {args.school_code}")
        campus = (await session.execute(select(Campus).where(Campus.tenant_id == tenant.id, Campus.name == args.campus_name))).scalar_one_or_none()
        if not campus:
            raise RuntimeError(f"校区不存在: {args.campus_name}")
        grade = (await session.execute(select(Grade).where(
            Grade.tenant_id == tenant.id,
            Grade.level == 1,
        ).order_by(Grade.id))).scalars().first()
        if not grade:
            raise RuntimeError("未找到高一年级基础年级")
        if grade.campus_id not in (None, campus.id):
            raise RuntimeError("高一年级基础年级不属于目标校区")
        units = (await session.execute(select(OrganizationUnit).where(
            OrganizationUnit.tenant_id == tenant.id,
            OrganizationUnit.unit_type == "grade_group",
            OrganizationUnit.grade_id == grade.id,
            OrganizationUnit.academic_year == args.academic_year,
            OrganizationUnit.status == "active",
        ))).scalars().all()
        if len(units) != 1:
            raise RuntimeError(f"目标学年有效高一年级部应为1个，实际为{len(units)}个")
        unit = units[0]

        all_students = (await session.execute(select(Student).where(Student.tenant_id == tenant.id))).scalars().all()
        existing_names = [s.name for s in all_students]
        target_students = [s for s in all_students if s.campus_id == campus.id and s.grade_id == grade.id and (s.student_no or "").startswith("CY1-G1-")]
        if len(target_students) > args.total:
            raise RuntimeError(f"当前已有{len(target_students)}名高一测试学生，大于目标{args.total}名；为避免误删，本次未修改数据")

        name_iter = unique_names(existing_names)
        existing_nos = {s.student_no for s in all_students if s.student_no}
        created = 0
        next_number = 1
        while len(target_students) < args.total:
            student_no = f"CY1-G1-{next_number:04d}"
            next_number += 1
            if student_no in existing_nos:
                continue
            student = Student(
                tenant_id=tenant.id,
                campus_id=campus.id,
                grade_id=grade.id,
                class_id=None,
                name=next(name_iter),
                gender="male" if next_number % 2 else "female",
                parent_phone=f"139000{10000 + next_number:05d}",
                height_cm=160 + (next_number % 25),
                student_no=student_no,
                roster_order=next_number,
                status="studying",
            )
            session.add(student)
            target_students.append(student)
            existing_nos.add(student_no)
            created += 1

        await session.flush()
        membership_columns = StudentGradeMembership.__table__.c
        memberships = (await session.execute(select(StudentGradeMembership).where(
            membership_columns.tenant_id == tenant.id,
            membership_columns.academic_year == args.academic_year,
        ))).scalars().all()
        membership_by_student = {m.student_id: m for m in memberships}
        membership_created = 0
        for student in target_students:
            membership = membership_by_student.get(student.id)
            if membership:
                membership.grade_id = grade.id
                membership.grade_unit_id = unit.id
                membership.cohort_label = args.cohort_label
                membership.status = "active"
            else:
                session.add(StudentGradeMembership(
                    tenant_id=tenant.id,
                    student_id=student.id,
                    grade_id=grade.id,
                    grade_unit_id=unit.id,
                    academic_year=args.academic_year,
                    cohort_label=args.cohort_label,
                    status="active",
                ))
                membership_created += 1
        await session.commit()
        print({"tenant_id": tenant.id, "campus_id": campus.id, "grade_id": grade.id, "grade_unit_id": unit.id, "target_students": len(target_students), "students_created": created, "memberships_created": membership_created, "class_id": None})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-code", default="gaokao312")
    parser.add_argument("--campus-name", default="崇仁一中")
    parser.add_argument("--academic-year", default="2026-2027")
    parser.add_argument("--cohort-label", default="2026届")
    parser.add_argument("--total", type=int, default=474)
    asyncio.run(main(parser.parse_args()))
