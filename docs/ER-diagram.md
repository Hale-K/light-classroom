# 轻课堂 · 核心 ER 关系图

> 覆盖组织架构 / 班级学生 / 排课任教 / 权限配置四大核心域(20 张表,全库共 63 张)。
> 实线 = 数据库外键;虚线 = 逻辑关联(未建 FK,应用层维护)。
> 所有业务表均含 `tenant_id`(多租户隔离),图上省略该字段以聚焦业务关系。

```mermaid
erDiagram
    %% ===== 组织与人员 =====
    TENANT ||--o{ CAMPUS : "拥有校区"
    TENANT ||--o{ "USER" : "教职工"
    TENANT ||--o{ GRADE : "年级"
    TENANT ||--o{ ORGANIZATION_UNIT : "组织架构"
    TENANT ||--o{ TENANT_CONFIG : "个性化配置"
    TENANT ||--o{ ROLE : "角色"

    CAMPUS ||--o{ BUILDING : "校区含楼栋"
    BUILDING ||--o{ ROOM : "楼栋含教室"
    CAMPUS ||--o{ GRADE : "年级属于校区"

    "USER" }o--o{ ROLE : "userrole 多对多"

    ORGANIZATION_UNIT |o--o{ ORGANIZATION_UNIT : "parent_id 自引用树"
    ORGANIZATION_UNIT ||--o{ STAFF_APPOINTMENT : "组织任职"
    "USER" ||--o{ STAFF_APPOINTMENT : "人员任职"

    %% ===== 年级 / 班级 / 学生 =====
    GRADE ||--o{ CLASS_ : "年级下设班级"
    CLASS_ ||--o{ STUDENT : "班级在读学生"
    GRADE |o--o{ STUDENT : "先定年级后分班"
    ROOM |o--o{ CLASS_ : "home_room 固定教室"
    "USER" |o--o{ CLASS_ : "head_teacher 班主任"

    %% ===== 排课域 =====
    CLASS_ ||--o{ TEACHING_ASSIGNMENT : "任教关系"
    SUBJECT ||--o{ TEACHING_ASSIGNMENT : "学科"
    "USER" ||--o{ TEACHING_ASSIGNMENT : "任课教师"
    CLASS_ ||--o{ SCHEDULE : "课表项"
    SUBJECT ||--o{ SCHEDULE : "课程学科"
    "USER" ||--o{ SCHEDULE : "授课教师"
    CLASS_ ||--o{ SEAT_ARRANGEMENT : "座位表"

    TENANT {
        int id PK
        string code UK "学校代码"
        string name "学校名称"
        string province "省份"
        string gaokao_mode "高考模式"
    }
    CAMPUS {
        int id PK
        int tenant_id FK
        string name UK "租户内唯一"
        string address
    }
    BUILDING {
        int id PK
        int campus_id FK
        string name "校区内唯一"
        int floor_count
    }
    ROOM {
        int id PK
        int building_id FK
        string name "楼栋内唯一"
        int capacity "容量"
        string room_type "classroom等"
        bool is_schedulable "可排课"
        bool is_exam_enabled "可作考场"
    }
    GRADE {
        int id PK
        int tenant_id FK
        int campus_id FK "可空"
        string name "如 高一年级(租户内唯一)"
        int level "1/2/3 层级"
    }
    CLASS_ {
        int id PK
        int tenant_id FK
        int grade_id FK
        string name "年级+届内唯一"
        string cohort_label "届(毕业年)"
        int head_teacher_id FK "班主任"
        int home_room_id FK "固定教室"
        string class_type "重点/普通等"
        int planned_student_count
    }
    STUDENT {
        int id PK
        int tenant_id FK
        int class_id FK "可空=待分班"
        int grade_id FK "可空"
        string name
        string student_no UK "租户内唯一"
        string status "studying/leave/…"
        string check_in_status "报到状态"
    }
    "USER" {
        int id PK
        int tenant_id FK
        string name
        string phone UK "登录账号(租户内唯一)"
        string role "基础角色"
        string status
    }
    SUBJECT {
        int id PK
        string name UK "全局字典:语数英物化生…"
    }
    ORGANIZATION_UNIT {
        int id PK
        int tenant_id FK
        int parent_id FK "自引用"
        int grade_id FK "可空"
        string name "父节点内唯一"
        string unit_type "department/grade_group/subject_group"
        string cohort_label "届(年级部)"
        string academic_year "任职学年"
        string status
    }
    STAFF_APPOINTMENT {
        int id PK
        int organization_unit_id FK
        int staff_id FK
        string position_code "member/grade_director…"
        string academic_year "可空=长期"
        string status
    }
    ROLE {
        int id PK
        int tenant_id FK "可空=内置"
        string code UK "teacher/head_teacher…"
        string name
    }
    TENANT_CONFIG {
        int id PK
        int tenant_id FK
        string config_key UK "配置键"
        json config_value
    }
    TEACHING_ASSIGNMENT {
        int id PK
        int tenant_id FK
        int class_id FK
        int subject_id FK
        int teacher_id FK
        string academic_year "学年"
        string term "学期"
        int weekly_periods "每周课时"
    }
    SCHEDULE {
        int id PK
        int tenant_id FK
        int class_id FK
        int subject_id FK
        int teacher_id FK "代课后指向代课教师"
        int weekday "星期1-7"
        int period "节次"
        string room "上课教室名"
        string academic_year
        string term
    }
    SEAT_ARRANGEMENT {
        int id PK
        int class_id FK
        int rows
        int cols
        json student_map "座位→学生映射"
        date effective_from "版本生效日"
    }
```

## 阅读指引

- **多租户**:所有业务表带 `tenant_id`,名称类唯一约束均为「租户内唯一」(class 是 租户+年级+届+班名)
- **届(cohort)**:`class.cohort_label` 存毕业年(如 2029);`organization_unit` 的年级部同款字段,两者对齐
- **组织树**:`organization_unit.parent_id` 自引用;「年级管理中心 → 年级部」靠 unit_type=`grade_group` + 标记识别;教师学科资质来自 `subject_group` 单元的任职
- **排课三键**:`teaching_assignment`(谁教哪个班哪科)→ `schedule`(具体排到周几第几节);`schedule.teacher_id` 可被"代课"功能改写,不改任教关系
- **软关联**:`class.head_teacher_id`、`class.home_room_id` 等为逻辑关联,数据库未建强外键,由应用层维护一致性
