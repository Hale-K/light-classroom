-- =====================================================
-- 2026-2027学年度上学期 高一年级任课教师安排
-- 基于老师提供的课表生成
-- 租户: gaokao312 (tenant_id=3)
-- =====================================================

-- =====================================================
-- 第一步: 删除旧的高一任教关系和课表
-- =====================================================
DELETE FROM schedule WHERE tenant_id = 3 AND class_id IN (
    SELECT id FROM class WHERE tenant_id = 3 AND grade_id IN (
        SELECT id FROM grade WHERE tenant_id = 3 AND level = 1
    )
);
DELETE FROM teachingassignment WHERE tenant_id = 3 AND class_id IN (
    SELECT id FROM class WHERE tenant_id = 3 AND grade_id IN (
        SELECT id FROM grade WHERE tenant_id = 3 AND level = 1
    )
);

-- =====================================================
-- 第二步: 插入新教师 (使用图片中的真实姓名)
-- =====================================================
-- 先检查教师是否已存在，不存在则插入
-- 教师ID将从现有最大ID+1开始自增

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '黄淑梅', 'phone_hsm', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '黄淑梅');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '杨元元', 'phone_yyy', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '杨元元');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '陈霞', 'phone_chenxia', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '陈霞');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '曹宁', 'phone_cn', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '曹宁');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '刘玉静', 'phone_lyj', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '刘玉静');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '李昕格', 'phone_lxg', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '李昕格');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '王亚军', 'phone_wyj', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '王亚军');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '王重雷', 'phone_wcl', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '王重雷');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '郑杰', 'phone_zj', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '郑杰');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '郭云明', 'phone_gym', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '郭云明');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '沐泳', 'phone_my', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '沐泳');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '马美佳', 'phone_mmj', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '马美佳');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '薛莹', 'phone_xy', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '薛莹');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '陈晓辉', 'phone_cxh', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '陈晓辉');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '姚芳', 'phone_yf', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '姚芳');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '王晶晶', 'phone_wjj', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '王晶晶');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '张卓', 'phone_zz', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '张卓');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '陈碧瑶', 'phone_cby', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '陈碧瑶');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '王印忠', 'phone_wyz', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '王印忠');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '张凯', 'phone_zk', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '张凯');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '孙岩', 'phone_sy', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '孙岩');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '张祥', 'phone_zxiang', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '张祥');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '褚光庆', 'phone_cgq', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '褚光庆');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '毛宇莹', 'phone_myy', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '毛宇莹');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '张佳楠', 'phone_zjn', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '张佳楠');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '黄丽娟', 'phone_hlj', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '黄丽娟');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '韩丹', 'phone_hd', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '韩丹');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '张琬羚', 'phone_zwl', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '张琬羚');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '李美霖', 'phone_lml', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '李美霖');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '张楠', 'phone_znan', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '张楠');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '韩东雪', 'phone_hdx', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '韩东雪');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '高思琦', 'phone_gsq', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '高思琦');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '田丽国', 'phone_tlg', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '田丽国');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '钟宇', 'phone_zy', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '钟宇');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '董靓洋', 'phone_djy', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '董靓洋');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '贾秀文', 'phone_jxw', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '贾秀文');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '屈金', 'phone_qj', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '屈金');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '王淑华', 'phone_wsh', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '王淑华');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '王璐', 'phone_wl', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '王璐');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '刘东铭', 'phone_ldm', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '刘东铭');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '宋词', 'phone_sc', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '宋词');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '赵永丽', 'phone_zyl', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '赵永丽');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '贺兰晴', 'phone_hlq', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '贺兰晴');

INSERT INTO "user" (tenant_id, name, phone, password_hash, role, status)
SELECT 3, '史雨暄', 'phone_syx', '$2b$12$placeholder', 'teacher', 'active'
WHERE NOT EXISTS (SELECT 1 FROM "user" WHERE tenant_id = 3 AND name = '史雨暄');

-- =====================================================
-- 第三步: 插入任教关系 (teachingassignment)
-- 学科ID: 1=语文, 2=数学, 3=英语, 4=物理, 5=化学, 6=生物, 7=政治, 8=历史, 9=地理, 11=体育
-- 班级ID: 579=高一(1)班, 580=高一(2)班, ..., 588=高一(10)班
-- 学年: 2026-2027, 学期: 1
-- =====================================================

-- ====== 高一(1)班 class_id=579 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='黄淑梅'), 1, 579, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王亚军'), 2, 579, '2026-2027', '1', 6, '541室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='薛莹'), 3, 579, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王印忠'), 4, 579, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张祥'), 5, 579, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='黄丽娟'), 6, 579, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张楠'), 8, 579, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='钟宇'), 7, 579, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='贾秀文'), 9, 579, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王璐'), 11, 579, '2026-2027', '1', 2, NULL;

-- ====== 高一(2)班 class_id=580 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='黄淑梅'), 1, 580, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王亚军'), 2, 580, '2026-2027', '1', 6, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='薛莹'), 3, 580, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王印忠'), 4, 580, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张祥'), 5, 580, '2026-2027', '1', 3, '433室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='黄丽娟'), 6, 580, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张楠'), 8, 580, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='钟宇'), 7, 580, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='屈金'), 9, 580, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王璐'), 11, 580, '2026-2027', '1', 2, NULL;

-- ====== 高一(3)班 class_id=581 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='杨元元'), 1, 581, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王重雷'), 2, 581, '2026-2027', '1', 6, '429室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='陈晓辉'), 3, 581, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王印忠'), 4, 581, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张祥'), 5, 581, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='韩丹'), 6, 581, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张楠'), 8, 581, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='钟宇'), 7, 581, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='贾秀文'), 9, 581, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='刘东铭'), 11, 581, '2026-2027', '1', 2, NULL;

-- ====== 高一(4)班 class_id=582 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='杨元元'), 1, 582, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='郑杰'), 2, 582, '2026-2027', '1', 6, '425室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='姚芳'), 3, 582, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张凯'), 4, 582, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='褚光庆'), 5, 582, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='韩丹'), 6, 582, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='高思琦'), 8, 582, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='钟宇'), 7, 582, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='屈金'), 9, 582, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='宋词'), 11, 582, '2026-2027', '1', 2, NULL;

-- ====== 高一(5)班 class_id=583 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='陈霞'), 1, 583, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='郭云明'), 2, 583, '2026-2027', '1', 6, '420室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='姚芳'), 3, 583, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='孙岩'), 4, 583, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='褚光庆'), 5, 583, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张琬羚'), 6, 583, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='韩东雪'), 8, 583, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='董靓洋'), 7, 583, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王淑华'), 9, 583, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='刘东铭'), 11, 583, '2026-2027', '1', 2, NULL;

-- ====== 高一(6)班 class_id=584 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='陈霞'), 1, 584, '2026-2027', '1', 5, '417室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王重雷'), 2, 584, '2026-2027', '1', 6, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王晶晶'), 3, 584, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张凯'), 4, 584, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='毛宇莹'), 5, 584, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='韩丹'), 6, 584, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张楠'), 8, 584, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='钟宇'), 7, 584, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='贾秀文'), 9, 584, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='宋词'), 11, 584, '2026-2027', '1', 2, NULL;

-- ====== 高一(7)班 class_id=585 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='曹宁'), 1, 585, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='沐泳'), 2, 585, '2026-2027', '1', 6, '410室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王晶晶'), 3, 585, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='孙岩'), 4, 585, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='褚光庆'), 5, 585, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='李美霖'), 6, 585, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='高思琦'), 8, 585, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='董靓洋'), 7, 585, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='屈金'), 9, 585, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='刘东铭'), 11, 585, '2026-2027', '1', 2, NULL;

-- ====== 高一(8)班 class_id=586 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='刘玉静'), 1, 586, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='郑杰'), 2, 586, '2026-2027', '1', 6, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张卓'), 3, 586, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张凯'), 4, 586, '2026-2027', '1', 3, '413室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='褚光庆'), 5, 586, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='李美霖'), 6, 586, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='田丽国'), 8, 586, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='董靓洋'), 7, 586, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='贾秀文'), 9, 586, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='宋词'), 11, 586, '2026-2027', '1', 2, NULL;

-- ====== 高一(9)班 class_id=587 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='李昕格'), 1, 587, '2026-2027', '1', 5, '409室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='马美佳'), 2, 587, '2026-2027', '1', 6, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='陈碧瑶'), 3, 587, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='孙岩'), 4, 587, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='毛宇莹'), 5, 587, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张琬羚'), 6, 587, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='田丽国'), 8, 587, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='董靓洋'), 7, 587, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='王淑华'), 9, 587, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='刘东铭'), 11, 587, '2026-2027', '1', 2, NULL;

-- ====== 高一(10)班 class_id=588 ======
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='李昕格'), 1, 588, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='郭云明'), 2, 588, '2026-2027', '1', 6, '420室';
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张卓'), 3, 588, '2026-2027', '1', 5, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='孙岩'), 4, 588, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='张佳楠'), 5, 588, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='李美霖'), 6, 588, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='韩东雪'), 8, 588, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='董靓洋'), 7, 588, '2026-2027', '1', 2, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='屈金'), 9, 588, '2026-2027', '1', 3, NULL;
INSERT INTO teachingassignment (tenant_id, teacher_id, subject_id, class_id, academic_year, term, weekly_periods, room)
SELECT 3, (SELECT id FROM "user" WHERE tenant_id=3 AND name='宋词'), 11, 588, '2026-2027', '1', 2, NULL;

-- =====================================================
-- 验证: 检查插入结果
-- =====================================================
SELECT
    c.name AS 班级,
    s.name AS 学科,
    u.name AS 教师,
    ta.weekly_periods AS 周课时
FROM teachingassignment ta
JOIN "user" u ON ta.teacher_id = u.id
JOIN subject s ON ta.subject_id = s.id
JOIN class c ON ta.class_id = c.id
WHERE ta.tenant_id = 3
  AND ta.academic_year = '2026-2027'
  AND ta.term = '1'
  AND c.grade_id IN (SELECT id FROM grade WHERE tenant_id = 3 AND level = 1)
ORDER BY c.id, s.id;
