"""班级规模与确定性学生命名的种子辅助函数（教学演示/测试用）。"""
UNIQUE_SURNAMES = (
    "王", "李", "张", "刘", "陈", "杨", "黄", "赵", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗",
    "梁", "宋", "郑", "谢", "韩", "唐", "冯", "于", "董", "萧",
    "程", "曹", "袁", "邓", "许", "傅", "沈", "曾", "彭", "吕",
    "苏", "卢", "蒋", "蔡", "贾", "丁", "魏", "薛", "叶", "阎",
    "余", "潘", "杜", "戴", "夏", "钟", "汪", "田", "任", "姜",
    "范", "方", "石", "姚", "谭", "廖", "邹", "熊", "金", "陆",
    "郝", "孔", "白", "崔", "康", "毛", "邱", "秦", "江", "史",
    "顾", "侯", "邵", "孟", "龙", "万", "段", "雷", "钱", "汤",
    "尹", "黎", "易", "常", "武", "乔", "贺", "赖", "龚", "文",
)
UNIQUE_GIVEN_NAMES = (
    "子涵", "宇轩", "浩然", "雨桐", "欣怡", "嘉怡", "梓轩", "思源", "明哲", "佳宁",
    "俊杰", "诗涵", "文博", "若曦", "泽宇", "梦瑶", "天佑", "语嫣", "奕辰", "可欣",
    "晨曦", "睿哲", "安然", "子墨", "思远", "嘉禾", "亦凡", "清妍", "景行", "知夏",
    "星辰", "书瑶", "锦程", "沐阳", "语桐", "皓轩", "婉清", "一诺", "予安", "云舒",
    "怀瑾", "知远", "允和", "令仪", "昭宁", "砚秋", "承宇", "以宁", "南乔", "君泽",
    "清越", "安歌", "望舒", "慕言", "时雨", "若安", "景明", "修远", "嘉言", "云帆",
)


def balanced_sizes(student_count: int, class_count: int) -> list[int]:
    """按班级分摊学生数，班间差最多 1 人。"""
    base, remainder = divmod(student_count, class_count)
    sizes = [base + 1] * remainder + [base] * (class_count - remainder)
    if not sizes or min(sizes) < 1 or max(sizes) > 45:
        raise ValueError(
            f"Invalid class plan: students={student_count}, classes={class_count}, sizes={sizes[:3]}"
        )
    return sizes


def grade_population(total: int, grade_count: int) -> list[int]:
    if total < 1 or grade_count < 1:
        raise ValueError("total and grade_count must be positive")
    base, remainder = divmod(total, grade_count)
    return [base + (1 if index < remainder else 0) for index in range(grade_count)]


def student_name(index: int) -> str:
    capacity = len(UNIQUE_SURNAMES) * len(UNIQUE_GIVEN_NAMES)
    if index < 0 or index >= capacity:
        raise ValueError(f"student name index must be between 0 and {capacity - 1}")
    surname = UNIQUE_SURNAMES[index % len(UNIQUE_SURNAMES)]
    given_name = UNIQUE_GIVEN_NAMES[index // len(UNIQUE_SURNAMES)]
    return surname + given_name
