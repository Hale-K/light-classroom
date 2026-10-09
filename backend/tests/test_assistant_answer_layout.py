from app.ai.tools.answer_layout import normalize_answer_markdown, answer_layout_error


def test_flattened_heading_and_table_are_recovered_without_changing_numbers():
    source = '给3个方案： #### 方案二（39节） | 科目 | 建议课时 | 说明 | | --- | ---: | --- | | 数学 | 6 | 主科 | | 体育 | 2 | 固定 | | 合计 | 8 | 建议 | #### 提醒 - 未修改数据'
    result = normalize_answer_markdown(source)
    assert '给3个方案：\n\n#### 方案二（39节）\n\n| 科目 | 建议课时 | 说明 |\n| --- | ---: | --- |' in result
    assert '| 数学 | 6 | 主科 |\n| 体育 | 2 | 固定 |\n| 合计 | 8 | 建议 |\n\n#### 提醒' in result
    assert answer_layout_error(result) is None
    # Layout repair cannot silently make an incorrect title into a correct one.
    assert '39节' in result


def test_canonical_table_is_stable_and_escaped_pipe_stays_in_one_cell():
    source = '已查询。\n\n| 科目 | 说明 |\n| --- | --- |\n| 数学 | A\\|B |\n| 体育 | — |'
    assert normalize_answer_markdown(source) == source


def test_fenced_example_and_unbalanced_rows_are_not_guessed():
    example = '```text\n#### 标题 | 科目 | 节数 | | --- | --- |\n```'
    assert normalize_answer_markdown(example) == example
    broken = '建议 | 科目 | 节数 | | --- | --- | | 数学 | 7 | 多出来的单元格 |'
    assert answer_layout_error(normalize_answer_markdown(broken))
