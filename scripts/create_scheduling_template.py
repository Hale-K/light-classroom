"""Generate the teacher-facing workbook; example rows never imply permission to import."""
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'frontend-react/public/templates/scheduling-configuration.xlsx'
book = Workbook()
guide = book.active
guide.title = '填写说明'
for row in [
    ['轻课堂排课配置模板', '版本 1'],
    ['使用方式', '先阅读说明，再填写数据表；示例放在独立工作表，不作为正式数据。'],
    ['基础范围', '填写学校内已有的年级、班级和教师名称，学年和学期需在导入时确认。'],
    ['科目', '每个科目一行；课程类型和晚自习资格必须明确。'],
    ['班级课时', '一个班级、一个科目、一个周类型一行；填写该班课时，不能填写教师多个班的总课时。'],
    ['任课关系', '一个教师、一个班级、一个科目一行；多班拆成多行，不填写1-10或1、2。'],
    ['半课时', '0.5课时需要明确单双周安排；不能由系统猜测哪一周上课。'],
    ['晚课', '单周晚课和双周晚课分别填0或1；教师总晚课不能直接作为班级晚课。'],
    ['排课规则', '每条规则一行；填写规则类型、对象及完整时间范围。星期用周一至周日，节次用数字。'],
    ['复杂规则', '选择其他并写完整说明；需要人工确认能否转换成系统支持的规则。'],
    ['名称标记', '教师姓名不带额外星号或注释；重名教师需在说明中提供可区分信息。'],
    ['空白含义', '空白表示未提供，不能当成0、允许或没有限制；不适用请在说明中写明。'],
    ['数据安全', '识别后先核对预览和冲突，再二次确认；不要把示例数据粘入正式表。已有不同配置不会覆盖。'],
    ['规则范围', '规则需明确年级。班级列当前留空，年级内单班限制请在规则工作台设置；连堂必须填写每周次数。'],
]: guide.append(row)

schemas = {
    '科目': ['科目', '课程类型', '晚自习资格', '说明'],
    '班级课时': ['年级', '班级', '科目', '工作日课时', '周六课时', '单双周', '单周晚课', '双周晚课', '说明'],
    '任课关系': ['年级', '班级', '科目', '教师', '说明'],
    '排课规则': ['规则类型', '适用对象类型', '适用对象名称', '年级', '班级', '星期', '节次', '数量', '约束强度', '规则说明', '每周次数'],
}
for title, headers in schemas.items():
    sheet = book.create_sheet(title)
    sheet.append(headers)
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = f'A1:{sheet.cell(1, len(headers)).column_letter}201'

def choices(sheet, column, values):
    validation = DataValidation(type='list', formula1='"' + ','.join(values) + '"', allow_blank=True)
    validation.errorTitle = '请使用模板选项'
    validation.error = '请从下拉列表选择；其他情况写入说明。'
    validation.showErrorMessage = True
    sheet.add_data_validation(validation)
    validation.add(f'{column}2:{column}201')

choices(book['科目'], 'B', ['学科课', '活动课'])
choices(book['科目'], 'C', ['允许', '不允许'])
choices(book['班级课时'], 'F', ['每周', '单周', '双周'])
for col in ['G', 'H']: choices(book['班级课时'], col, ['0', '1'])
choices(book['排课规则'], 'A', ['教师禁排', '科目禁排', '固定课节', '连堂', '每天课时上限', '其他'])
choices(book['排课规则'], 'B', ['教师', '科目', '班级'])
choices(book['排课规则'], 'I', ['必须满足', '尽量满足'])

examples = book.create_sheet('示例_请勿导入')
for row in [
    ['表名', '填写示例', '说明'],
    ['科目', '语文｜学科课｜允许', '明确类型和资格'],
    ['班级课时', '高一｜高一（1）班｜语文｜5｜1｜每周｜1｜1', '该班工作日5节、周六1节；晚课单列'],
    ['任课关系', '高一｜高一（1）班｜语文｜示例教师', '第二个班另写一行'],
    ['排课规则', '教师禁排｜教师｜示例教师｜高一｜（班级留空）｜周一｜1、2｜｜必须满足', '在高一年级规则组生效'],
    ['排课规则', '连堂｜科目｜物理｜高一｜（班级留空）｜｜｜2｜尽量满足｜每周次数1', '每周尽量安排一次连续两节物理课'],
    ['原表换算', '教师两个班共10节工作日课时，不能直接各填10节', '仅在确认两班均分后各填5；不均分则填写真实值'],
]: examples.append(row)

for sheet in book:
    sheet.row_dimensions[1].height = 30
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='168FC5')
    for row in sheet:
        for cell in row: cell.alignment = Alignment(vertical='top', wrap_text=True)
    for column in sheet.columns:
        letter = column[0].column_letter
        sheet.column_dimensions[letter].width = 22
    if sheet.title in ['填写说明', '示例_请勿导入']:
        sheet.column_dimensions['B'].width = 85
        sheet.column_dimensions['C'].width = 55
        for index in range(2, sheet.max_row + 1): sheet.row_dimensions[index].height = 45
    else:
        sheet.column_dimensions[sheet.cell(1, sheet.max_column).column_letter].width = 55
TARGET.parent.mkdir(parents=True, exist_ok=True)
book.save(TARGET)
print(TARGET)
